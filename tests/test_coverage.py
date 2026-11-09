"""The rule check: which catalogued fields each packaged rule level supplies, and its verdict."""

from __future__ import annotations

import polars as pl
import pytest

from apb_catalog.coverage import catalogues, coverage_of, rule_coverage
from apb_catalog.rules import rule_levels
from apb_catalog.source import (
    CatalogueDescription,
    Evidence,
    Key,
    ProducerCatalogue,
    RequirementRow,
    RuleVariant,
    SourceCatalogue,
    SourceCatalogues,
    SourceEntry,
)
from apb_catalog.vocabulary import Qualifier, SetVocabulary

DESCRIPTION = CatalogueDescription(purpose="Test entries.", used_by=("tests",))
PATTERN = "^2\\..*"
ION = RuleVariant(level="peptidoform_ion", software_version_pattern=PATTERN)
REQUIRED = (
    RequirementRow(level="peptidoform_ion", location="var", key="group", requirement="required"),
    RequirementRow(level="peptidoform_ion", location="var", key="charge", requirement="required"),
    RequirementRow(level="peptidoform_ion", location="var", key="decoy", requirement="optional"),
)
KEYS = tuple(
    Key(key=kind, kind=kind) for kind in ("group", "charge", "decoy", "contaminant", "peptidoform")
)
VOCABULARY = SetVocabulary(
    prefix="toy",
    definition="A synthetic field the tests look up.",
    kind_definition="Which synthetic field.",
    kinds=dict.fromkeys(
        ("group", "charge", "decoy", "contaminant", "peptidoform", "unknown"), "test"
    ),
    qualifiers={
        "origin": Qualifier(
            definition="Who writes the field.",
            values=dict.fromkeys(("vendor", "apb2", "apb_fasta", "unknown"), "test"),
        ),
    },
)


def _entry(name: str, kind: str, origin: str = "vendor", location: str = "var") -> SourceEntry:
    table = "fasta_validation" if location == "varm" else None
    return SourceEntry.model_validate(
        {
            "entry_id": f"{origin}.peptidoform_ion.{name}",
            "software_version_pattern": [PATTERN] if origin == "vendor" else [],
            "reference": {
                "level": "peptidoform_ion",
                "location": location,
                "name": name,
                "table": table,
            },
            "key": kind,
            "kind": kind,
            "qualifiers": {"origin": origin},
            "evidence": Evidence(basis="test"),
        }
    )


def _sources(
    *entries: SourceEntry, producers: tuple[ProducerCatalogue, ...] = ()
) -> SourceCatalogues:
    vendor = SourceCatalogue(
        software_name="DIA-NN",
        variants=(ION,),
        entries=entries,
    )
    return SourceCatalogues(
        VOCABULARY, "test", (vendor,), DESCRIPTION, producers, (), REQUIRED, KEYS
    )


def _producer(*entries: SourceEntry, requires: tuple[str, ...] = ()) -> ProducerCatalogue:
    return ProducerCatalogue(
        producer="tool",
        requires=requires,
        instruction="run `tool`" if requires else None,
        entries=entries,
    )


GROUP = _entry("Protein_Group", "group")
CHARGE = _entry("Precursor_Charge", "charge")
DECOY = _entry("apb_Decoy", "decoy")


@pytest.mark.parametrize(
    ("entries", "verdict"),
    [((GROUP,), "fail"), ((GROUP, CHARGE), "pass"), ((GROUP, CHARGE, DECOY), "pass")],
)
def test_a_missing_required_field_fails_and_a_missing_optional_one_passes(
    entries: tuple[SourceEntry, ...], verdict: str
) -> None:
    """The level verdict follows the strongest requirement it misses."""
    coverage = coverage_of(_sources(*entries))
    assert set(coverage.get_column("verdict")) == {verdict}
    assert coverage.get_column("kind").to_list() == ["group", "charge", "decoy"]


def test_unsupported_fields_name_their_requirement_and_no_column() -> None:
    """A required field nothing answers is a row of its own, with no column."""
    missing = coverage_of(_sources(GROUP)).filter(pl.col("column").is_null())
    assert missing.select("kind", "requirement").rows() == [
        ("charge", "required"),
        ("decoy", "optional"),
    ]


def test_a_missing_optional_field_passes_and_is_still_listed() -> None:
    """An optional field nothing answers leaves the level passing, as a row with no column."""
    coverage = coverage_of(_sources(GROUP, CHARGE))
    assert set(coverage.get_column("verdict")) == {"pass"}
    missing = coverage.filter(pl.col("column").is_null())
    assert missing.select("kind", "requirement").rows() == [("decoy", "optional")]


def test_an_app_field_counts_on_every_level_of_every_software() -> None:
    """The catalog reads no rule, so an app's field counts wherever the app has an entry."""
    flag = _entry("is_unique", "peptidoform", origin="apb_fasta")
    coverage = coverage_of(_sources(GROUP, producers=(_producer(flag),)))
    assert coverage.filter(pl.col("producer") == "tool").select("column", "needs").rows() == [
        ("is_unique", None)
    ]


def test_a_later_producer_counts_with_what_to_run() -> None:
    """A field apb-fasta adds after conversion counts, and says what writes it."""
    flag = _entry("fasta_matches_contaminant", "contaminant", "apb_fasta", "varm")
    producer = _producer(flag, requires=("fasta", "provenance"))
    row = coverage_of(_sources(GROUP, producers=(producer,))).filter(
        pl.col("kind") == "contaminant"
    )
    assert row.select("table", "column", "needs").rows() == [
        ("fasta_validation", "fasta_matches_contaminant", "run `tool`")
    ]


def test_requirements_must_name_the_sets_keys() -> None:
    """A requirement for a key the set does not list is refused."""
    vendor = SourceCatalogue(
        software_name="DIA-NN",
        variants=(ION,),
        entries=(GROUP,),
    )
    row = RequirementRow(level="peptidoform_ion", location="var", key="fdr", requirement="required")
    with pytest.raises(ValueError, match="unknown key 'fdr'"):
        SourceCatalogues(VOCABULARY, "test", (vendor,), DESCRIPTION, (), (), (row,), KEYS)


def test_a_requirement_row_matches_its_key() -> None:
    """The abundance set's recommended row asks for an un-normalized intensity, not any intensity."""
    coverage = rule_coverage("abundance_alpha").filter(pl.col("software") == "FragPipe")
    missing = coverage.filter(pl.col("column").is_null())
    assert missing.select("key", "kind", "qualifiers", "requirement").rows() == [
        ("intensity", "intensity", "normalization=none", "recommended")
    ]
    assert "intensity_norm_settings" in coverage.get_column("key").to_list()
    assert set(coverage.get_column("verdict")) == {"warn"}


def test_a_set_without_requirements_reports_coverage_only() -> None:
    """Confidence catalogues judge nothing; a level without entries still has one row."""
    coverage = rule_coverage("confidence_alpha")
    assert coverage.get_column("verdict").is_null().all()
    assert not coverage.filter(pl.col("kind").is_null()).is_empty()


def test_every_packaged_set_is_listed() -> None:
    """The abundance and apb sets set requirements; every set has entries."""
    listed = catalogues()
    assert listed.get_column("catalogue").to_list() == [
        "abundance_alpha",
        "confidence_alpha",
        "proteobench_entrapment_alpha",
        "apb_alpha",
        "obs_annotation_alpha",
        "fasta_peptides_alpha",
        "fasta_proteins_alpha",
        "chromatography_alpha",
    ]
    requirements = [True, False, False, True, False, False, False, False]
    assert listed.get_column("has_requirements").to_list() == requirements
    assert (listed.get_column("entries") > 0).all()


def test_an_unknown_set_is_refused() -> None:
    """The error names the packaged sets."""
    with pytest.raises(ValueError, match="packaged"):
        rule_coverage("nope")


def test_every_packaged_rule_level_carries_the_apb_must_fields() -> None:
    """The apb set reviews every packaged rule level; none fails."""
    coverage = rule_coverage("apb_alpha")
    assert coverage.filter(pl.col("verdict") == "fail").is_empty()
    checked = set(coverage.select("software", "software_version_pattern", "level").iter_rows())
    assert checked == {
        (found.software_name, found.software_version_pattern, found.level)
        for found in rule_levels()
    }
