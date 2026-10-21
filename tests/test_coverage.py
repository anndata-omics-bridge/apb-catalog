"""The rule check: which catalogued fields each packaged rule level supplies, and its verdict."""

from __future__ import annotations

import polars as pl
import pytest

from apb_catalog.coverage import catalogues, coverage_of, rule_coverage
from apb_catalog.source import (
    CatalogueDescription,
    Evidence,
    ProducerCatalogue,
    Requirement,
    RuleVariant,
    SourceCatalogue,
    SourceCatalogues,
    SourceEntry,
    VocabularyExtension,
)
from apb_catalog.vocabulary import Vocabulary, packaged_vocabulary
from tests.conftest import TESTS

DESCRIPTION = CatalogueDescription(purpose="Test entries.", used_by=("tests",))
RULE = "diann/v2/rules.json"
ION = RuleVariant(rule=RULE, level="ion", software_version_pattern="^2\\..*")
REQUIRED: dict[str, dict[str, Requirement]] = {
    "ion": {"group": "MUST", "charge": "MUST", "decoy": "MAY"}
}
VOCABULARY = Vocabulary(
    vocabulary_version="test",
    concepts={
        **packaged_vocabulary().concepts,
        **VocabularyExtension.model_validate_json(
            (TESTS / "toy_set" / "vocabulary.json").read_text("utf-8")
        ).concepts,
    },
)


def _entry(name: str, kind: str, origin: str = "vendor", location: str = "var") -> SourceEntry:
    table = "fasta_validation" if location == "varm" else None
    return SourceEntry.model_validate(
        {
            "entry_id": f"{origin}.ion.{name}",
            "rules": [RULE] if origin == "vendor" else [],
            "reference": {"level": "ion", "location": location, "name": name, "table": table},
            "concept": "toy",
            "qualifiers": {"kind": kind, "origin": origin},
            "evidence": Evidence(basis="test"),
        }
    )


def _sources(
    *entries: SourceEntry, producers: tuple[ProducerCatalogue, ...] = ()
) -> SourceCatalogues:
    vendor = SourceCatalogue(
        catalogue_id="diann",
        catalogue_version="0.1",
        software_name="DIA-NN",
        variants=(ION,),
        entries=entries,
    )
    return SourceCatalogues(VOCABULARY, (vendor,), DESCRIPTION, producers, REQUIRED)


def _producer(*entries: SourceEntry, requires: tuple[str, ...] = ()) -> ProducerCatalogue:
    return ProducerCatalogue(
        catalogue_id="tool",
        catalogue_version="0.1",
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
    [((GROUP,), "fail"), ((GROUP, CHARGE), "warn"), ((GROUP, CHARGE, DECOY), "pass")],
)
def test_a_missing_must_fails_and_a_missing_may_warns(
    entries: tuple[SourceEntry, ...], verdict: str
) -> None:
    """The level verdict follows the strongest requirement it misses."""
    coverage = coverage_of(_sources(*entries))
    assert set(coverage.get_column("verdict")) == {verdict}
    assert coverage.get_column("kind").to_list() == ["group", "charge", "decoy"]


def test_unsupported_fields_name_their_requirement_and_no_column() -> None:
    """A required field nothing answers is a row of its own, with no column."""
    missing = coverage_of(_sources(GROUP)).filter(pl.col("column").is_null())
    assert missing.select("kind", "requirement").rows() == [("charge", "MUST"), ("decoy", "MAY")]


def test_computed_columns_name_their_vendor_inputs() -> None:
    """``apb_Decoy`` is computed from DIA-NN's ``Decoy``; the row names that input."""
    decoy = coverage_of(_sources(GROUP, CHARGE, DECOY)).filter(pl.col("kind") == "decoy")
    assert decoy.get_column("inputs").to_list() == [["Decoy"]]


def test_a_producer_field_counts_only_where_the_rule_retains_its_column() -> None:
    """APB2 writes ``ProForma_peptidoform`` on DIA-NN ions, but no ``ProForma_fragment`` there."""
    kept = _entry("ProForma_peptidoform", "peptidoform", origin="apb2")
    absent = _entry("ProForma_fragment", "charge", origin="apb2")
    coverage = coverage_of(_sources(GROUP, producers=(_producer(kept, absent),)))
    assert coverage.filter(pl.col("producer") == "tool").get_column("column").to_list() == [
        "ProForma_peptidoform"
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


def test_requirements_must_name_vocabulary_kinds() -> None:
    """A requirement for a kind the concept does not define is refused."""
    vendor = SourceCatalogue(
        catalogue_id="diann",
        catalogue_version="0.1",
        software_name="DIA-NN",
        variants=(ION,),
        entries=(GROUP,),
    )
    with pytest.raises(ValueError, match="unknown kinds"):
        SourceCatalogues(VOCABULARY, (vendor,), DESCRIPTION, (), {"ion": {"fdr": "MUST"}})


def test_a_set_without_requirements_reports_coverage_only() -> None:
    """Confidence catalogues judge nothing; a level without entries still has one row."""
    coverage = rule_coverage("identification_confidence")
    assert coverage.get_column("verdict").is_null().all()
    assert not coverage.filter(pl.col("kind").is_null()).is_empty()


def test_every_packaged_set_is_listed() -> None:
    """No packaged set sets requirements; every set has entries."""
    listed = catalogues()
    assert listed.get_column("catalogue").to_list() == [
        "identification_confidence",
        "proteobench_entrapment",
    ]
    assert not listed.get_column("has_requirements").any()
    assert (listed.get_column("entries") > 0).all()


def test_an_unknown_set_is_refused() -> None:
    """The error names the packaged sets."""
    with pytest.raises(ValueError, match="packaged"):
        rule_coverage("nope")
