"""Callers ask a result for a meaning and get the data; snapshots survive every format."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest
from apb2.api import (
    JsonValue,
    ParsedLevel,
    ParsedLevels,
    read_parsed_levels,
    write_parsed_levels,
)
from polars.testing import assert_frame_equal
from pydantic import ValidationError

from apb_catalog.catalog import (
    METADATA_KEY,
    Catalog,
    attach_snapshot,
    stale_levels,
    stored_snapshot,
)
from apb_catalog.resolver import ReviewedBinding, UnresolvedField, UnreviewedBinding
from apb_catalog.source import packaged_descriptions
from tests.packaged_rules import declared_rule_json

type VarColumns = Mapping[str, Sequence[float] | Sequence[str] | Sequence[bool]]

KEYS: dict[str, str] = {"peptidoform_ion": "ProForma_ion", "protein": "Protein_Group"}
FASTA_RAN: dict[str, JsonValue] = {"fasta": {"provenance": {"peptide_verification": {}}}}
FASTA_CONTAMINANTS = {
    "fasta_validation": pl.DataFrame({"fasta_matches_contaminant": [True, False]})
}


def _level(
    level: str,
    rule_json: str | None,
    layers: Sequence[str],
    var: VarColumns,
    varm: Mapping[str, pl.DataFrame] | None = None,
) -> ParsedLevel:
    obs = pl.DataFrame({"Run": ["R1", "R2", "R3"]})
    key = KEYS[level]
    features = pl.DataFrame(
        {key: ["F1", "F2"], **{name: list(values) for name, values in var.items()}}
    )
    values = {
        name: pl.DataFrame(
            {f"c{column}": [float(offset + 1) / 10 + column] * 2 for column in range(obs.height)}
        )
        for offset, name in enumerate(layers)
    }
    uns: dict[str, JsonValue] = {}
    if rule_json is not None:
        uns["provenance"] = {"rule_json": rule_json}
    return ParsedLevel.build(
        obs,
        ("Run",),
        features,
        (key,),
        {},
        primary_layer=layers[0],
        abundance=values,
        uns=uns,
        varm=varm,
    )


def _result(
    rule: str | None,
    layers: Sequence[str],
    var: VarColumns | None = None,
    level: str = "peptidoform_ion",
    varm: Mapping[str, pl.DataFrame] | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> ParsedLevels:
    rule_json = declared_rule_json(rule, level) if rule is not None else None
    return ParsedLevels(
        levels={level: _level(level, rule_json, layers, var or {}, varm)},
        uns={},
        metadata=metadata or {},
    )


def _edited_maxquant(**changes: object) -> ParsedLevels:
    edited = json.loads(declared_rule_json("maxquant_wide/rules.json", "peptidoform_ion"))
    edited.update(changes)
    return ParsedLevels(
        levels={
            "peptidoform_ion": _level(
                "peptidoform_ion", json.dumps(edited), ["Intensity", "PEP"], {}
            )
        },
        uns={},
    )


MAXQUANT = ("maxquant_wide/rules.json", ["Intensity", "PEP", "Score"])
SPECTRONAUT = ("spectronaut/rules.json", ["FG_Quantity", "EG_PEP", "EG_Qvalue", "FG_Qvalue"])


def test_the_same_call_returns_each_vendors_layer() -> None:
    """Callers never name ``PEP`` or ``EG_PEP``; the catalogue does."""
    maxquant = _result(*MAXQUANT)
    spectronaut = _result(*SPECTRONAUT)
    pep = {"concept": "confidence", "kind": "pep"}
    assert (
        Catalog(maxquant, "identification_confidence").layer("peptidoform_ion", **pep)
        is maxquant.levels["peptidoform_ion"].layers["PEP"]
    )
    found = Catalog(spectronaut, "identification_confidence").layer("peptidoform_ion", **pep)
    assert found is spectronaut.levels["peptidoform_ion"].layers["EG_PEP"]


def test_only_the_fields_the_consumer_needs_are_catalogued() -> None:
    """Spectronaut's EG and FG q-values agree; aggregation is given the EG one only."""
    parsed = _result(*SPECTRONAUT)
    found = Catalog(parsed, "identification_confidence").layer(
        "peptidoform_ion", concept="confidence", kind="q_value"
    )
    assert found is parsed.levels["peptidoform_ion"].layers["EG_Qvalue"]


def test_a_vendor_without_the_field_returns_none() -> None:
    """DIA-NN without its PEP layer is a reviewed absence, not an error."""
    parsed = _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"])
    catalog = Catalog(parsed, "identification_confidence")
    assert catalog.layer("peptidoform_ion", concept="confidence", kind="pep") is None
    assert (
        catalog.layer("peptidoform_ion", concept="confidence", kind="q_value")
        is parsed.levels["peptidoform_ion"].layers["Q_Value"]
    )


def test_quantification_confidence_is_found_only_when_asked_for() -> None:
    """Sage's q-value rates the MS1 peak, one value per feature."""
    parsed = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    catalog = Catalog(parsed, "identification_confidence")
    assert catalog.var("peptidoform_ion", concept="confidence", kind="q_value") is None
    column = catalog.var(
        "peptidoform_ion", concept="confidence", kind="q_value", stage="quantification"
    )
    assert column is not None
    assert column.to_list() == [0.001, 0.002]


DIANN_ION = {
    "ProForma_peptidoform": ["PEPTIDE", "PEPTIDEK"],
    "Precursor_Charge": [2.0, 3.0],
    "Protein_Group": ["P1", "P1;P2"],
    "apb_Decoy": [False, False],
}


def test_a_plugin_set_answers_like_a_packaged_one(toy_set: str) -> None:
    """An installed set's vendor and APB2 fields are found by their kinds."""
    parsed = _result("diann/v2/rules.json", ["Ms1_Normalised", "Q_Value"], DIANN_ION)
    catalog = Catalog(parsed, toy_set)
    assert catalog.var("peptidoform_ion", concept="toy", origin="vendor") == (
        "charge",
        "decoy",
        "group",
    )
    assert catalog.var("peptidoform_ion", concept="toy", origin="apb2") == ("peptidoform",)
    group = catalog.var("peptidoform_ion", concept="toy", kind="group")
    assert group is not None
    assert group.to_list() == ["P1", "P1;P2"]
    assert catalog.description.used_by == ("apb-catalog tests",)


def test_a_later_producers_field_is_unknown_until_it_runs(toy_set: str) -> None:
    """A FASTA-based field never reads as absent before apb-fasta had a chance to write it."""
    catalog = Catalog(_result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION), toy_set)
    with pytest.raises(UnresolvedField, match=r"apb-fasta has not run.*apb-fasta verify-peptides"):
        catalog.var("peptidoform_ion", concept="toy", kind="contaminant")


def test_a_producer_field_reads_its_varm_table(toy_set: str) -> None:
    """After apb-fasta, the contaminant flag comes from its feature-aligned varm table."""
    parsed = _result(
        "diann/v2/rules.json",
        ["Ms1_Normalised"],
        DIANN_ION,
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    catalog = Catalog(parsed, toy_set)
    flag = catalog.var("peptidoform_ion", concept="toy", kind="contaminant")
    assert flag is not None
    assert flag.to_list() == [True, False]
    tables = catalog.fields().filter(pl.col("kind") == "contaminant").get_column("table")
    assert tables.to_list() == ["fasta_validation"]


def test_origin_chooses_between_the_vendor_and_a_producer(toy_set: str) -> None:
    """FragPipe marks its own contaminants and apb-fasta marks the FASTA's: both answer."""
    parsed = _result(
        "fragpipe/rules.json",
        ["Intensity"],
        {"apb_Contaminant": [False, True]},
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    catalog = Catalog(parsed, toy_set)
    with pytest.raises(UnresolvedField, match="ambiguous"):
        catalog.var("peptidoform_ion", concept="toy", kind="contaminant")
    vendor = catalog.var("peptidoform_ion", concept="toy", kind="contaminant", origin="vendor")
    fasta = catalog.var("peptidoform_ion", concept="toy", kind="contaminant", origin="apb_fasta")
    assert vendor is not None and vendor.to_list() == [False, True]
    assert fasta is not None and fasta.to_list() == [True, False]


def test_a_vendor_without_its_own_flag_offers_none(toy_set: str) -> None:
    """DIA-NN marks no contaminants itself, so only apb-fasta can answer them."""
    catalog = Catalog(_result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION), toy_set)
    assert (
        catalog.var("peptidoform_ion", concept="toy", kind="contaminant", origin="vendor") is None
    )


def test_a_varm_lookup_survives_storage(toy_set: str, tmp_path: Path) -> None:
    """A snapshot naming a varm table reads back identically."""
    parsed = _result(
        "diann/v2/rules.json",
        ["Ms1_Normalised"],
        DIANN_ION,
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    catalog = Catalog(parsed, toy_set)
    catalog.var("peptidoform_ion", concept="toy", kind="contaminant")
    snapshot = catalog.snapshot()
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)
    assert stored_snapshot(read_parsed_levels(target), toy_set) == snapshot


def test_an_unknown_catalogue_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown catalogue"):
        Catalog(_result(*MAXQUANT), "everything")


def test_an_unreviewed_level_raises() -> None:
    """Without a reviewed rule the catalogue cannot even claim absence."""
    with pytest.raises(UnresolvedField, match=r"unknown.*rule_json"):
        Catalog(_result(None, ["Intensity"]), "identification_confidence").layer(
            "peptidoform_ion", concept="confidence", kind="pep"
        )


def test_an_unreviewed_software_version_is_unknown() -> None:
    """A software version no catalogue variant names answers unknown."""
    with pytest.raises(UnresolvedField, match="no source catalogue reviewed"):
        Catalog(
            _edited_maxquant(software_version_pattern="^99\\."), "identification_confidence"
        ).layer("peptidoform_ion", concept="confidence", kind="pep")


def test_an_edited_rule_keeps_its_entries() -> None:
    """Levels bind by software and version, so editing a rule within a version changes nothing."""
    parsed = _edited_maxquant(file_version=-1)
    pep = Catalog(parsed, "identification_confidence").layer(
        "peptidoform_ion", concept="confidence", kind="pep"
    )
    assert pep is parsed.levels["peptidoform_ion"].layers["PEP"]


def test_an_absent_level_returns_none() -> None:
    """Asking about a level the result lacks is answered, not raised."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    assert catalog.layer("peptide", concept="confidence", kind="pep") is None


def test_an_unknown_kind_or_concept_is_rejected() -> None:
    """Misspellings fail loudly instead of matching nothing."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    with pytest.raises(ValueError, match="does not admit"):
        catalog.layer("peptidoform_ion", concept="confidence", kind="pepp")
    with pytest.raises(ValueError, match="unknown concept"):
        catalog.layer("peptidoform_ion", concept="retention", kind="raw")


def test_leaving_out_kind_lists_the_kinds_on_offer() -> None:
    """Without ``kind`` the catalogue says what a level holds for the concept."""
    assert Catalog(_result(*MAXQUANT), "identification_confidence").layer(
        "peptidoform_ion", concept="confidence"
    ) == ("pep",)
    spectronaut = Catalog(_result(*SPECTRONAUT), "identification_confidence")
    assert spectronaut.layer("peptidoform_ion", concept="confidence") == ("pep", "q_value")
    dia_nn = Catalog(
        _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"]),
        "identification_confidence",
    )
    assert dia_nn.layer("peptidoform_ion", concept="confidence") == ("q_value",)
    assert dia_nn.var("peptidoform_ion", concept="confidence") is None


def test_listing_kinds_on_an_absent_or_unreviewed_level() -> None:
    """An absent level offers nothing; an unreviewed one cannot say."""
    assert (
        Catalog(_result(*MAXQUANT), "identification_confidence").layer(
            "peptide", concept="confidence"
        )
        is None
    )
    with pytest.raises(UnresolvedField, match="unknown"):
        Catalog(_result(None, ["Intensity"]), "identification_confidence").layer(
            "peptidoform_ion", concept="confidence"
        )


def test_listing_kinds_is_not_recorded_as_a_lookup() -> None:
    """Only lookups that return data enter the snapshot."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    catalog.layer("peptidoform_ion", concept="confidence")
    assert catalog.snapshot().resolutions == ()


def test_fields_lists_what_the_result_holds() -> None:
    """One row per catalogued field, readable without knowing the vendor."""
    fields = Catalog(_result(*MAXQUANT), "identification_confidence").fields()
    assert fields.select("location", "name", "kind").rows() == [("layers", "PEP", "pep")]


def test_the_snapshot_records_its_catalogue_bindings_and_lookups() -> None:
    """Every lookup is kept for the persisted record."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    catalog.layer("peptidoform_ion", concept="confidence", kind="pep")
    catalog.layer("peptidoform_ion", concept="confidence", kind="q_value")
    snapshot = catalog.snapshot()
    assert snapshot.catalogue == "identification_confidence"
    assert [resolution.status for resolution in snapshot.resolutions] == ["resolved", "missing"]
    binding = snapshot.levels[0]
    assert isinstance(binding, ReviewedBinding)
    assert (binding.software_name, binding.rule) == ("MaxQuant", "maxquant_wide/rules.json")
    unreviewed = Catalog(_result(None, ["Intensity"]), "identification_confidence").snapshot()
    assert isinstance(unreviewed.levels[0], UnreviewedBinding)


def test_snapshots_of_two_catalogues_sit_side_by_side() -> None:
    """Attaching one set's snapshot keeps the other's, and the input stays unchanged."""
    parsed = _result(*MAXQUANT)
    confidence = Catalog(parsed, "identification_confidence").snapshot()
    entrapment = Catalog(parsed, "proteobench_entrapment").snapshot()
    attached = attach_snapshot(attach_snapshot(parsed, confidence), entrapment)
    assert METADATA_KEY not in parsed.metadata
    assert stored_snapshot(parsed, "identification_confidence") is None
    assert stored_snapshot(attached, "identification_confidence") == confidence
    assert stored_snapshot(attached, "proteobench_entrapment") == entrapment
    assert attached.levels["peptidoform_ion"].layers is parsed.levels["peptidoform_ion"].layers
    assert METADATA_KEY not in attached.levels["peptidoform_ion"].metadata, (
        "no request, no level summary"
    )


def _with_namespace(parsed: ParsedLevels, namespace: JsonValue) -> ParsedLevels:
    return replace(parsed, metadata={**parsed.metadata, METADATA_KEY: namespace})


def test_attaching_keeps_unrelated_namespace_entries() -> None:
    """Attaching adds this catalogue's snapshot and leaves every other entry as it was."""
    parsed = _with_namespace(_result(*MAXQUANT), {"other": {"contract": "elsewhere"}})
    snapshot = Catalog(parsed, "identification_confidence").snapshot()

    attached = attach_snapshot(parsed, snapshot)

    assert attached.metadata[METADATA_KEY] == {
        "other": {"contract": "elsewhere"},
        "identification_confidence": {"result": snapshot.model_dump(mode="json")},
    }
    assert parsed.metadata[METADATA_KEY] == {"other": {"contract": "elsewhere"}}


@pytest.mark.parametrize("namespace", [["prior-evidence"], "prior-evidence", 3, None])
def test_a_malformed_namespace_raises_instead_of_being_replaced(namespace: JsonValue) -> None:
    """A present namespace that is not an object is never read as absent or overwritten."""
    parsed = _with_namespace(_result(*MAXQUANT), namespace)
    snapshot = Catalog(parsed, "identification_confidence").snapshot()

    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        attach_snapshot(parsed, snapshot)
    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        stored_snapshot(parsed, "identification_confidence")
    assert parsed.metadata[METADATA_KEY] == namespace


@pytest.mark.parametrize(
    "stored", [None, ["prior-evidence"], {"contract": "apb-catalog-resolution"}]
)
def test_a_malformed_selected_snapshot_fails_validation(stored: JsonValue) -> None:
    """A catalogue's own entry is validated, so a null or broken snapshot is not absent."""
    parsed = _with_namespace(_result(*MAXQUANT), {"identification_confidence": stored})

    with pytest.raises(ValidationError):
        stored_snapshot(parsed, "identification_confidence")


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_a_stored_malformed_namespace_still_raises(tmp_path: Path, suffix: str) -> None:
    """Valid JSON of the wrong shape survives storage, so reading it back must still raise."""
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(_with_namespace(_result(*MAXQUANT), ["prior-evidence"]), target)
    restored = read_parsed_levels(target)
    snapshot = Catalog(restored, "identification_confidence").snapshot()

    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        attach_snapshot(restored, snapshot)
    assert restored.metadata[METADATA_KEY] == ["prior-evidence"]


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_snapshots_round_trip_every_storage_format(tmp_path: Path, suffix: str) -> None:
    """Stored snapshots read back identically and leave the scientific data untouched."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed, "identification_confidence")
    catalog.layer("peptidoform_ion", concept="confidence", kind="pep")
    snapshot = catalog.snapshot()
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)

    restored = read_parsed_levels(target)

    assert stored_snapshot(restored, "identification_confidence") == snapshot
    assert stale_levels(restored, snapshot) == ()
    for name, table in parsed.levels["peptidoform_ion"].layers.items():
        assert_frame_equal(restored.levels["peptidoform_ion"].layers[name].wide(), table.wide())


def test_a_stored_snapshot_is_readable_as_plain_json(tmp_path: Path) -> None:
    """Consumers can follow the contract with apb2 and the standard library alone."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed, "identification_confidence")
    catalog.layer("peptidoform_ion", concept="confidence", kind="pep")
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, catalog.snapshot()), target)

    namespace: dict[str, Any] = json.loads(
        json.dumps(read_parsed_levels(target).metadata["catalog"])
    )
    stored = namespace["identification_confidence"]["result"]

    assert stored["contract"] == "apb-catalog-resolution"
    answer = stored["resolutions"][0]
    assert answer["status"] == "resolved"
    assert answer["reference"] == {
        "level": "peptidoform_ion",
        "location": "layers",
        "name": "PEP",
        "table": None,
    }
    entry = next(entry for entry in stored["entries"] if entry["reference"] == answer["reference"])
    assert entry["qualifiers"]["kind"] == "pep"


def test_a_changed_software_version_makes_the_snapshot_stale() -> None:
    """Snapshots record the software and version they were resolved against."""
    snapshot = Catalog(_result(*MAXQUANT), "identification_confidence").snapshot()
    assert stale_levels(_edited_maxquant(file_version=-1), snapshot) == ()
    stale = _edited_maxquant(software_version_pattern="^99\\.")
    assert stale_levels(stale, snapshot) == ("peptidoform_ion",)
    assert stale_levels(ParsedLevels(levels={}, uns={}), snapshot) == ("peptidoform_ion",)


def test_every_packaged_set_states_its_purpose_and_users() -> None:
    """Each sources directory has a description, and each description a sources directory."""
    sources = resources.files("apb_catalog").joinpath("data", "sources")
    directories = {path.name for path in sources.iterdir() if path.is_dir()}
    descriptions = packaged_descriptions()
    assert set(descriptions) == directories
    assert all(d.purpose and d.used_by for d in descriptions.values())


def test_snapshot_embeds_the_set_description() -> None:
    """A snapshot reader learns what the set is for without the package."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    assert catalog.snapshot().description == catalog.description
    assert "apb-aggregate" in catalog.description.used_by[0]


def test_proteobench_entrapment_offers_each_precursor_q_value_as_its_own_kind() -> None:
    """Entrapment ranks by run, library or experiment-wide q-values; each is one kind.

    The run's q-value is a layer; the library's and the experiment-wide one are one value per
    precursor, so DIA-NN's rule stores them in var.
    """
    library = [0.01, 0.02]
    parsed = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised", "Q_Value", "PEP"],
        var={"Lib_Q_Value": library, "Global_Q_Value": [0.01, 0.03]},
    )
    catalog = Catalog(parsed, "proteobench_entrapment")
    assert catalog.layer("peptidoform_ion", concept="confidence") == ("q_value",)
    assert catalog.var("peptidoform_ion", concept="confidence") == (
        "global_q_value",
        "library_q_value",
    )
    found = catalog.var("peptidoform_ion", concept="confidence", kind="library_q_value")
    assert found is not None
    assert (found.name, found.to_list()) == ("Lib_Q_Value", library)
    assert catalog.layer("peptidoform_ion", concept="confidence", kind="pep") is None, (
        "PEP is not ranked by"
    )
    assert (
        Catalog(_result(*MAXQUANT), "proteobench_entrapment").layer(
            "peptidoform_ion", concept="confidence"
        )
        is None
    )


def test_abundance_finds_the_un_normalized_layer_where_one_exists() -> None:
    """DIA-NN writes its precursor quantity before and after normalization; PEAKS only after."""
    layers = ["Precursor_Normalised", "Precursor_Quantity", "Ms1_Area", "Ms1_Normalised"]
    parsed = _result("diann/v1_8/rules.json", layers)
    catalog = Catalog(parsed, "abundance")
    ion = parsed.levels["peptidoform_ion"].layers
    raw = catalog.layer("peptidoform_ion", kind="intensity", normalization="none")
    assert raw is ion["Precursor_Quantity"]
    normalized = catalog.layer(
        "peptidoform_ion", concept="abundance", kind="intensity", normalization="run_setting"
    )
    assert normalized is ion["Precursor_Normalised"]
    peaks = Catalog(_result("peaks/rules.json", ["Normalized_Area"]), "abundance")
    assert peaks.layer("peptidoform_ion", kind="intensity", normalization="none") is None


def test_an_undocumented_normalization_is_unknown_not_missing() -> None:
    """A consumer can tell a layer nobody documented from a layer that does not exist."""
    catalog = Catalog(_result("fragpipe/rules.json", ["Intensity"]), "abundance")
    with pytest.raises(UnresolvedField) as raised:
        catalog.layer(
            "peptidoform_ion", concept="abundance", kind="intensity", normalization="none"
        )
    assert raised.value.resolution.status == "unknown"


def test_the_british_spelling_of_the_qualifier_is_rejected() -> None:
    """``normalisation`` has no alias; the error names the qualifiers the concept declares."""
    catalog = Catalog(_result("diann/v1_8/rules.json", ["Precursor_Quantity"]), "abundance")
    with pytest.raises(ValueError, match=r"'normalisation'; declared: \['kind', 'normalization'\]"):
        catalog.layer("peptidoform_ion", kind="intensity", normalisation="none")


def test_the_concept_defaults_to_the_one_the_set_names() -> None:
    """Each packaged set names one concept, so a lookup needs only the kind; the snapshot
    still records the concept."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed, "identification_confidence")
    assert (
        catalog.layer("peptidoform_ion", kind="pep")
        is parsed.levels["peptidoform_ion"].layers["PEP"]
    )
    assert catalog.snapshot().resolutions[0].request.concept == "confidence"


def test_leaving_out_kind_and_concept_lists_the_kinds() -> None:
    """Without either, a level lists the kinds of the set's one concept."""
    spectronaut = Catalog(_result(*SPECTRONAUT), "identification_confidence")
    assert spectronaut.layer("peptidoform_ion") == ("pep", "q_value")
    sage = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    assert Catalog(sage, "identification_confidence").var(
        "peptidoform_ion", stage="quantification"
    ) == ("q_value",)


def test_kind_may_come_second_without_its_keyword() -> None:
    """``layer("peptidoform_ion", "pep")`` reads the second argument as the kind, for layers and var."""
    parsed = _result(*MAXQUANT)
    assert (
        Catalog(parsed, "identification_confidence").layer("peptidoform_ion", "pep")
        is parsed.levels["peptidoform_ion"].layers["PEP"]
    )
    sage = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    column = Catalog(sage, "identification_confidence").var(
        "peptidoform_ion", "q_value", stage="quantification"
    )
    assert column is not None
    assert column.to_list() == [0.001, 0.002]


def test_a_set_naming_two_concepts_needs_concept(two_concept_set: str) -> None:
    """A plugin may add a concept; once a set's entries name two, a lookup must choose one."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed, two_concept_set)
    with pytest.raises(ValueError, match=r"\['confidence', 'toy_signal'\]; pass concept="):
        catalog.layer("peptidoform_ion", kind="pep")
    with pytest.raises(ValueError, match="pass concept="):
        catalog.var("peptidoform_ion")
    ion = parsed.levels["peptidoform_ion"].layers
    assert catalog.layer("peptidoform_ion", kind="pep", concept="confidence") is ion["PEP"]
    assert catalog.layer("peptidoform_ion", "intensity", "toy_signal") is ion["Intensity"]
    assert catalog.layer("peptidoform_ion", concept="toy_signal") == ("intensity",)


def test_each_level_counts_the_requests_its_snapshot_answered() -> None:
    """A level record says how many lookups resolved, were missing, or stayed unresolved."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    catalog.layer("peptidoform_ion", concept="confidence", kind="pep")
    catalog.layer("peptidoform_ion", concept="confidence", kind="q_value")

    attached = attach_snapshot(_result(*MAXQUANT), catalog.snapshot())

    records = cast(dict[str, Any], attached.levels["peptidoform_ion"].metadata[METADATA_KEY])
    assert [
        (entry["name"], entry["value"], entry["status"])
        for entry in records["identification_confidence"]["summary"]
    ] == [
        ("resolved_requests", 1, "ok"),
        ("missing_requests", 1, "ok"),
        ("unresolved_requests", 0, "ok"),
    ]
