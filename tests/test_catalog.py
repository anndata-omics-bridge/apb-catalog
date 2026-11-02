"""Callers ask a result for a meaning and get the data; snapshots survive every format."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from importlib import resources
from pathlib import Path
from typing import Any, cast

import numpy as np
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
    DataCatalog,
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
    pep = {"key": "pep"}
    assert (
        DataCatalog(maxquant, "confidence").layer("peptidoform_ion", **pep)
        is maxquant.levels["peptidoform_ion"].layers["PEP"]
    )
    found = DataCatalog(spectronaut, "confidence").layer("peptidoform_ion", **pep)
    assert found is spectronaut.levels["peptidoform_ion"].layers["EG_PEP"]


def test_only_the_fields_the_consumer_needs_are_catalogued() -> None:
    """Spectronaut's EG and FG q-values agree; aggregation is given the EG one only."""
    parsed = _result(*SPECTRONAUT)
    found = DataCatalog(parsed, "confidence").layer("peptidoform_ion", key="q_value")
    assert found is parsed.levels["peptidoform_ion"].layers["EG_Qvalue"]


def test_a_vendor_without_the_field_returns_none() -> None:
    """DIA-NN without its PEP layer is a reviewed absence, not an error."""
    parsed = _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"])
    catalog = DataCatalog(parsed, "confidence")
    assert catalog.layer("peptidoform_ion", key="pep") is None
    assert (
        catalog.layer("peptidoform_ion", key="q_value")
        is parsed.levels["peptidoform_ion"].layers["Q_Value"]
    )


def test_quantification_confidence_is_found_only_when_asked_for() -> None:
    """Sage's q-value rates the MS1 peak, one value per feature."""
    parsed = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    catalog = DataCatalog(parsed, "confidence")
    assert catalog.var("peptidoform_ion", key="q_value") is None
    column = catalog.var("peptidoform_ion", key="quantification_q_value")
    assert column is not None
    assert column.to_list() == [0.001, 0.002]
    with pytest.raises(ValueError, match="q_value fixes stage"):
        catalog.var("peptidoform_ion", key="q_value", stage="quantification")


DIANN_ION = {
    "ProForma_peptidoform": ["PEPTIDE", "PEPTIDEK"],
    "Precursor_Charge": [2.0, 3.0],
    "Protein_Group": ["P1", "P1;P2"],
    "apb_Decoy": [False, False],
}


def test_a_plugin_set_answers_like_a_packaged_one(toy_set: str) -> None:
    """An installed set's vendor and APB2 fields are found by their kinds."""
    parsed = _result("diann/v2/rules.json", ["Ms1_Normalised", "Q_Value"], DIANN_ION)
    catalog = DataCatalog(parsed, toy_set)
    assert catalog.keys("peptidoform_ion", "var", origin="vendor") == ("charge", "decoy", "group")
    assert catalog.keys("peptidoform_ion", "var", origin="apb2") == ("peptidoform",)
    group = catalog.var("peptidoform_ion", key="group")
    assert group is not None
    assert group.to_list() == ["P1", "P1;P2"]
    assert catalog.description.used_by == ("apb-catalog tests",)


def test_a_later_producers_field_is_unknown_until_it_runs(toy_set: str) -> None:
    """A FASTA-based field never reads as absent before apb-fasta had a chance to write it."""
    catalog = DataCatalog(_result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION), toy_set)
    with pytest.raises(UnresolvedField, match=r"apb-fasta has not run.*apb-fasta verify-peptides"):
        catalog.var("peptidoform_ion", key="contaminant")


def test_a_producer_field_reads_its_varm_table(toy_set: str) -> None:
    """After apb-fasta, the contaminant flag comes from its feature-aligned varm table."""
    parsed = _result(
        "diann/v2/rules.json",
        ["Ms1_Normalised"],
        DIANN_ION,
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    catalog = DataCatalog(parsed, toy_set)
    flag = catalog.var("peptidoform_ion", key="contaminant")
    assert flag is not None
    assert flag.to_list() == [True, False]
    fields = catalog.fields().filter(pl.col("present"))
    tables = fields.filter(pl.col("kind") == "contaminant").get_column("table")
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
    catalog = DataCatalog(parsed, toy_set)
    with pytest.raises(UnresolvedField, match="ambiguous"):
        catalog.var("peptidoform_ion", key="contaminant")
    vendor = catalog.var("peptidoform_ion", key="contaminant", origin="vendor")
    fasta = catalog.var("peptidoform_ion", key="contaminant", origin="apb_fasta")
    assert vendor is not None and vendor.to_list() == [False, True]
    assert fasta is not None and fasta.to_list() == [True, False]


def test_a_vendor_without_its_own_flag_offers_none(toy_set: str) -> None:
    """DIA-NN marks no contaminants itself, so only apb-fasta can answer them."""
    catalog = DataCatalog(_result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION), toy_set)
    assert catalog.var("peptidoform_ion", key="contaminant", origin="vendor") is None


def test_a_varm_lookup_survives_storage(toy_set: str, tmp_path: Path) -> None:
    """A snapshot naming a varm table reads back identically."""
    parsed = _result(
        "diann/v2/rules.json",
        ["Ms1_Normalised"],
        DIANN_ION,
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    catalog = DataCatalog(parsed, toy_set)
    catalog.var("peptidoform_ion", key="contaminant")
    snapshot = catalog.snapshot()
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)
    assert stored_snapshot(read_parsed_levels(target), toy_set) == snapshot


def test_an_unknown_catalogue_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown catalogue"):
        DataCatalog(_result(*MAXQUANT), "everything")


def test_an_unreviewed_level_raises() -> None:
    """Without a reviewed rule the catalogue cannot even claim absence."""
    with pytest.raises(UnresolvedField, match=r"unknown.*rule_json"):
        DataCatalog(_result(None, ["Intensity"]), "confidence").layer("peptidoform_ion", key="pep")


def test_an_unreviewed_software_version_is_unknown() -> None:
    """A software version no catalogue variant names answers unknown."""
    with pytest.raises(UnresolvedField, match="no source catalogue reviewed"):
        DataCatalog(_edited_maxquant(software_version_pattern="^99\\."), "confidence").layer(
            "peptidoform_ion", key="pep"
        )


def test_an_edited_rule_keeps_its_entries() -> None:
    """Levels bind by software and version, so editing a rule within a version changes nothing."""
    parsed = _edited_maxquant(file_version=-1)
    pep = DataCatalog(parsed, "confidence").layer("peptidoform_ion", key="pep")
    assert pep is parsed.levels["peptidoform_ion"].layers["PEP"]


def test_an_absent_level_returns_none() -> None:
    """Asking about a level the result lacks is answered, not raised."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence")
    assert catalog.layer("peptide", key="pep") is None


def test_an_unknown_key_is_rejected() -> None:
    """Misspellings fail loudly instead of matching nothing."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence")
    with pytest.raises(ValueError, match="unknown key 'pepp'"):
        catalog.layer("peptidoform_ion", key="pepp")


def test_keys_lists_what_a_level_offers() -> None:
    """``keys`` says what a level holds at one location."""
    assert DataCatalog(_result(*MAXQUANT), "confidence").keys("peptidoform_ion", "layers") == (
        "pep",
    )
    spectronaut = DataCatalog(_result(*SPECTRONAUT), "confidence")
    assert spectronaut.keys("peptidoform_ion", "layers") == ("pep", "q_value")
    dia_nn = DataCatalog(
        _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"]), "confidence"
    )
    assert dia_nn.keys("peptidoform_ion", "layers") == ("q_value",)
    assert dia_nn.keys("peptidoform_ion", "var") == ("peptidoform_ion",), "apb's, always in"
    sage = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    assert DataCatalog(sage, "confidence").keys("peptidoform_ion", "var") == (
        "peptidoform_ion",
        "quantification_q_value",
    )
    assert (
        DataCatalog(sage, "confidence").keys("peptidoform_ion", "var", stage="identification") == ()
    )


def test_listing_keys_on_an_absent_or_unreviewed_level() -> None:
    """An absent level offers nothing; an unreviewed one cannot say."""
    assert DataCatalog(_result(*MAXQUANT), "confidence").keys("peptide", "layers") == ()
    with pytest.raises(UnresolvedField, match="unknown"):
        DataCatalog(_result(None, ["Intensity"]), "confidence").keys("peptidoform_ion", "layers")


def test_listing_keys_is_not_recorded_as_a_lookup() -> None:
    """Only lookups that return data enter the snapshot."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence")
    catalog.keys("peptidoform_ion", "layers")
    assert catalog.snapshot().resolutions == ()


def test_fields_lists_what_the_result_holds() -> None:
    """One row per catalogued field of every composed set, readable without knowing the vendor."""
    fields = DataCatalog(_result(*MAXQUANT), "confidence").fields().filter(pl.col("present"))
    assert fields.select("set", "location", "name", "kind").rows() == [
        ("confidence", "layers", "PEP", "pep"),
        ("apb", "var", "ProForma_ion", "peptidoform_ion"),
    ]


def test_the_snapshot_records_its_catalogue_bindings_and_lookups() -> None:
    """Every lookup is kept for the persisted record."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence")
    catalog.layer("peptidoform_ion", key="pep")
    catalog.layer("peptidoform_ion", key="q_value")
    snapshot = catalog.snapshot()
    assert snapshot.catalogue == "confidence"
    assert [resolution.status for resolution in snapshot.resolutions] == ["resolved", "missing"]
    binding = snapshot.levels[0]
    assert isinstance(binding, ReviewedBinding)
    assert (binding.software_name, binding.software_version_pattern) == (
        "MaxQuant",
        "^(1\\.5|1\\.6|2\\.)",
    )
    unreviewed = DataCatalog(_result(None, ["Intensity"]), "confidence").snapshot()
    assert isinstance(unreviewed.levels[0], UnreviewedBinding)


def test_snapshots_of_two_catalogues_sit_side_by_side() -> None:
    """Attaching one set's snapshot keeps the other's, and the input stays unchanged."""
    parsed = _result(*MAXQUANT)
    confidence = DataCatalog(parsed, "confidence").snapshot()
    entrapment = DataCatalog(parsed, "proteobench_entrapment").snapshot()
    attached = attach_snapshot(attach_snapshot(parsed, confidence), entrapment)
    assert METADATA_KEY not in parsed.metadata
    assert stored_snapshot(parsed, "confidence") is None
    assert stored_snapshot(attached, "confidence") == confidence
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
    snapshot = DataCatalog(parsed, "confidence").snapshot()

    attached = attach_snapshot(parsed, snapshot)

    assert attached.metadata[METADATA_KEY] == {
        "other": {"contract": "elsewhere"},
        "confidence": {"result": snapshot.model_dump(mode="json")},
    }
    assert parsed.metadata[METADATA_KEY] == {"other": {"contract": "elsewhere"}}


@pytest.mark.parametrize("namespace", [["prior-evidence"], "prior-evidence", 3, None])
def test_a_malformed_namespace_raises_instead_of_being_replaced(namespace: JsonValue) -> None:
    """A present namespace that is not an object is never read as absent or overwritten."""
    parsed = _with_namespace(_result(*MAXQUANT), namespace)
    snapshot = DataCatalog(parsed, "confidence").snapshot()

    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        attach_snapshot(parsed, snapshot)
    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        stored_snapshot(parsed, "confidence")
    assert parsed.metadata[METADATA_KEY] == namespace


@pytest.mark.parametrize(
    "stored", [None, ["prior-evidence"], {"contract": "apb-catalog-resolution"}]
)
def test_a_malformed_selected_snapshot_fails_validation(stored: JsonValue) -> None:
    """A catalogue's own entry is validated, so a null or broken snapshot is not absent."""
    parsed = _with_namespace(_result(*MAXQUANT), {"confidence": stored})

    with pytest.raises(ValidationError):
        stored_snapshot(parsed, "confidence")


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_a_stored_malformed_namespace_still_raises(tmp_path: Path, suffix: str) -> None:
    """Valid JSON of the wrong shape survives storage, so reading it back must still raise."""
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(_with_namespace(_result(*MAXQUANT), ["prior-evidence"]), target)
    restored = read_parsed_levels(target)
    snapshot = DataCatalog(restored, "confidence").snapshot()

    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        attach_snapshot(restored, snapshot)
    assert restored.metadata[METADATA_KEY] == ["prior-evidence"]


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_snapshots_round_trip_every_storage_format(tmp_path: Path, suffix: str) -> None:
    """Stored snapshots read back identically and leave the scientific data untouched."""
    parsed = _result(*MAXQUANT)
    catalog = DataCatalog(parsed, "confidence")
    catalog.layer("peptidoform_ion", key="pep")
    snapshot = catalog.snapshot()
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)

    restored = read_parsed_levels(target)

    assert stored_snapshot(restored, "confidence") == snapshot
    assert stale_levels(restored, snapshot) == ()
    for name, table in parsed.levels["peptidoform_ion"].layers.items():
        assert_frame_equal(restored.levels["peptidoform_ion"].layers[name].wide(), table.wide())


def test_a_stored_snapshot_is_readable_as_plain_json(tmp_path: Path) -> None:
    """Consumers can follow the contract with apb2 and the standard library alone."""
    parsed = _result(*MAXQUANT)
    catalog = DataCatalog(parsed, "confidence")
    catalog.layer("peptidoform_ion", key="pep")
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, catalog.snapshot()), target)

    namespace: dict[str, Any] = json.loads(
        json.dumps(read_parsed_levels(target).metadata["catalog"])
    )
    stored = namespace["confidence"]["result"]

    assert stored["contract"] == "apb-catalog-resolution"
    answer = stored["resolutions"][0]
    assert answer["status"] == "resolved"
    assert answer["reference"] == {
        "level": "peptidoform_ion",
        "location": "layers",
        "name": "PEP",
        "table": None,
        "prefix": None,
    }
    entry = next(entry for entry in stored["entries"] if entry["reference"] == answer["reference"])
    assert entry["qualifiers"]["kind"] == "pep"


def test_a_changed_software_version_makes_the_snapshot_stale() -> None:
    """Snapshots record the software and version they were resolved against."""
    snapshot = DataCatalog(_result(*MAXQUANT), "confidence").snapshot()
    assert stale_levels(_edited_maxquant(file_version=-1), snapshot) == ()
    stale = _edited_maxquant(software_version_pattern="^99\\.")
    assert stale_levels(stale, snapshot) == ("peptidoform_ion",)
    assert stale_levels(ParsedLevels(levels={}, uns={}), snapshot) == ("peptidoform_ion",)


def test_every_packaged_set_states_its_purpose_and_users() -> None:
    """Each set with entries has a description, and each description entries."""
    text = resources.files("apb_catalog").joinpath("data", "entries.csv").read_text("utf-8")
    described = {row["set"] for row in csv.DictReader(io.StringIO(text))}
    descriptions = packaged_descriptions()
    assert set(descriptions) == described
    assert all(d.purpose and d.used_by for d in descriptions.values())


def test_snapshot_embeds_the_set_description() -> None:
    """A snapshot reader learns what the set is for without the package."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence")
    assert catalog.snapshot().description == catalog.description
    assert "apb-aggregate" in catalog.description.used_by[0]


def test_proteobench_entrapment_offers_each_precursor_q_value_by_key_and_location() -> None:
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
    catalog = DataCatalog(parsed, "proteobench_entrapment")
    assert catalog.keys("peptidoform_ion", "layers") == ("q_value",)
    assert catalog.keys("peptidoform_ion", "var") == (
        "library_q_value",
        "peptidoform_ion",
        "q_value",
    )
    found = catalog.var("peptidoform_ion", key="library_q_value")
    assert found is not None
    assert (found.name, found.to_list()) == ("Lib_Q_Value", library)
    experiment = catalog.var("peptidoform_ion", key="q_value")
    assert experiment is not None
    assert experiment.name == "Global_Q_Value"
    assert catalog.layer("peptidoform_ion", key="pep") is None, "PEP is not ranked by"
    assert (
        DataCatalog(_result(*MAXQUANT), "proteobench_entrapment").keys("peptidoform_ion", "layers")
        == ()
    )


def test_abundance_finds_the_un_normalized_layer_where_one_exists() -> None:
    """DIA-NN writes its precursor quantity before and after normalization; PEAKS only after."""
    layers = ["Precursor_Normalised", "Precursor_Quantity", "Ms1_Area", "Ms1_Normalised"]
    parsed = _result("diann/v1_8/rules.json", layers)
    catalog = DataCatalog(parsed, "abundance")
    ion = parsed.levels["peptidoform_ion"].layers
    assert catalog.layer("peptidoform_ion", key="intensity") is ion["Precursor_Quantity"]
    normalized = catalog.layer("peptidoform_ion", key="normalized_intensity")
    assert normalized is ion["Precursor_Normalised"]
    peaks = DataCatalog(_result("peaks/rules.json", ["Normalized_Area"]), "abundance")
    assert peaks.layer("peptidoform_ion", key="intensity") is None


def test_an_undocumented_normalization_has_its_own_key() -> None:
    """A layer nobody documented the normalization of is not offered as an un-normalized one:
    asking for that is unknown, and its own key finds it."""
    catalog = DataCatalog(_result("fragpipe/rules.json", ["Intensity"]), "abundance")
    assert catalog.keys("peptidoform_ion", "layers") == ("intensity_unknown_normalization",)
    with pytest.raises(UnresolvedField, match="leaves normalization unknown"):
        catalog.layer("peptidoform_ion", key="intensity")
    found = catalog.layer("peptidoform_ion", key="intensity_unknown_normalization")
    assert found is not None
    assert found.layer_name == "Intensity"


def test_a_key_fixes_its_kind_and_qualifiers() -> None:
    """The key names the normalization, so a qualifier keyword may not restate or contradict it."""
    catalog = DataCatalog(_result("diann/v1_8/rules.json", ["Precursor_Quantity"]), "abundance")
    with pytest.raises(ValueError, match="intensity fixes normalization"):
        catalog.layer("peptidoform_ion", key="intensity", normalization="none")
    with pytest.raises(ValueError, match="fixes kind"):
        catalog.layer("peptidoform_ion", key="maxlfq", kind="maxlfq")
    with pytest.raises(ValueError, match="ask by key"):
        catalog.keys("peptidoform_ion", "layers", kind="intensity")


def test_the_key_may_come_second_without_its_keyword() -> None:
    """``layer("peptidoform_ion", "pep")`` reads the second argument as the key, for layers and var."""
    parsed = _result(*MAXQUANT)
    assert (
        DataCatalog(parsed, "confidence").layer("peptidoform_ion", "pep")
        is parsed.levels["peptidoform_ion"].layers["PEP"]
    )
    sage = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    column = DataCatalog(sage, "confidence").var("peptidoform_ion", "quantification_q_value")
    assert column is not None
    assert column.to_list() == [0.001, 0.002]


def test_each_level_counts_the_requests_its_snapshot_answered() -> None:
    """A level record says how many lookups resolved, were missing, or stayed unresolved."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence")
    catalog.layer("peptidoform_ion", key="pep")
    catalog.layer("peptidoform_ion", key="q_value")

    attached = attach_snapshot(_result(*MAXQUANT), catalog.snapshot())

    records = cast(dict[str, Any], attached.levels["peptidoform_ion"].metadata[METADATA_KEY])
    assert [
        (entry["name"], entry["value"], entry["status"])
        for entry in records["confidence"]["summary"]
    ] == [
        ("resolved_requests", 1, "ok"),
        ("missing_requests", 1, "ok"),
        ("unresolved_requests", 0, "ok"),
        ("missing_required_requests", 0, "ok"),
    ]


DIANN_LEVEL = {"ProForma_ion": ["PEPTIDE/2", "PEPTIDEK/3"], "Precursor_Charge": [2, 3]}


def _levels() -> tuple[ParsedLevels, DataCatalog]:
    parsed = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised", "Precursor_Quantity", "Q_Value"],
        DIANN_LEVEL,
    )
    return parsed, DataCatalog(parsed, "abundance", "confidence")


def test_a_level_answers_a_key_with_the_matrix_anndata_holds() -> None:
    """Observations by variables, numpy, as AnnData's layers; built once and shared."""
    parsed, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    intensity = level.layers["intensity"]
    expected = parsed.levels["peptidoform_ion"].layers["Precursor_Quantity"].wide().to_numpy().T
    assert isinstance(intensity, np.ndarray)
    assert intensity.shape == (3, 2)
    np.testing.assert_array_equal(intensity, expected)
    assert level.layers["intensity"] is intensity
    assert level.layers["normalized_intensity"] is level.X, "the primary layer is X"


def test_a_name_that_is_no_key_reads_the_levels_own_field() -> None:
    """As cf_xarray: a key first, then the level's own name, else KeyError."""
    _, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    assert level.layers["Q_Value"] is level.layers["q_value"]
    assert level.var["Precursor_Charge"].to_list() == [2, 3]
    assert level.var["peptidoform_ion"].to_list() == ["PEPTIDE/2", "PEPTIDEK/3"], "apb's key"
    with pytest.raises(KeyError, match="nonsense"):
        level.layers["nonsense"]
    with pytest.raises(KeyError, match="Precursor_Normalised"):
        level.layers["Precursor_Normalised"]  # the primary layer is X, not one of the layers


def test_keys_and_in_know_the_catalogs_keys_only() -> None:
    """Vendor names are read but not listed, as cf_xarray's keys()."""
    _, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    assert level.layers.keys() == {"intensity", "normalized_intensity", "q_value"}
    assert "intensity" in level.layers
    assert "Q_Value" not in level.layers
    assert level.var.keys() == {"peptidoform_ion"}


def test_obs_and_var_names_join_the_key_columns() -> None:
    """One name per observation and variable, polars, not pandas."""
    _, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    assert level.var_names.to_list() == ["PEPTIDE/2", "PEPTIDEK/3"]
    assert level.obs_names.dtype == pl.String
    assert level.obs_names.len() == level.X.shape[0]


def test_apb_is_always_in() -> None:
    """A data catalog of one set still answers APB's own fields."""
    _, catalog = _levels()
    assert (
        DataCatalog(_levels()[0], "confidence").var("peptidoform_ion", "peptidoform_ion")
        is not None
    )
    assert catalog.snapshot().catalogue == "abundance", "the first set named"
    assert catalog.snapshot("apb").catalogue == "apb"
