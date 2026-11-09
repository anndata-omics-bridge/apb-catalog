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

from apb_catalog.catalog import (
    METADATA_KEY,
    DataCatalog,
    attach_snapshot,
)
from apb_catalog.resolver import ReviewedBinding, UnresolvedField, UnreviewedBinding
from apb_catalog.snapshot import ResolutionSnapshot
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
    maxquant = DataCatalog(_result(*MAXQUANT), "confidence_alpha").levels["peptidoform_ion"]
    spectronaut = DataCatalog(_result(*SPECTRONAUT), "confidence_alpha").levels["peptidoform_ion"]
    assert maxquant.layers.name("pep") == "PEP"
    assert spectronaut.layers.name("pep") == "EG_PEP"


def test_only_the_fields_the_consumer_needs_are_catalogued() -> None:
    """Spectronaut's EG and FG q-values agree; aggregation is given the EG one only."""
    parsed = _result(*SPECTRONAUT)
    layers = DataCatalog(parsed, "confidence_alpha").levels["peptidoform_ion"].layers
    assert layers.name("q_value") == "EG_Qvalue"


def test_a_vendor_without_the_field_returns_none() -> None:
    """DIA-NN without its PEP layer is a reviewed absence, not an error."""
    parsed = _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"])
    catalog = DataCatalog(parsed, "confidence_alpha")
    assert catalog.levels["peptidoform_ion"].layers.get("pep") is None
    assert catalog.levels["peptidoform_ion"].layers.name("q_value") == "Q_Value"


def test_quantification_confidence_is_found_only_when_asked_for() -> None:
    """Sage's q-value rates the MS1 peak, one value per feature; the confidence set's
    ``q_value``, asked with its prefix, is no such value."""
    parsed = _result("sage/rules.json", ["Intensity"], {"q_value": [0.001, 0.002]})
    var = DataCatalog(parsed, "confidence_alpha").levels["peptidoform_ion"].var
    assert var.get("c:q_value") is None
    column = var.get("quantification_q_value")
    assert column is not None
    assert column.to_list() == [0.001, 0.002]
    with pytest.raises(ValueError, match="q_value fixes stage"):
        var.get("q_value", stage="quantification")


def test_a_prefix_tells_a_key_from_the_vendor_column_of_its_name() -> None:
    """Sage names its column ``q_value``: a plain name falls back to it, ``c:`` never reads it
    and ``v:`` always does."""
    parsed = _result("sage/rules.json", ["Intensity"], {"q_value": [0.001, 0.002]})
    var = DataCatalog(parsed, "confidence_alpha", "apb_alpha").levels["peptidoform_ion"].var
    assert var.name("q_value") == "q_value"
    assert var.name("v:q_value") == "q_value"
    assert var.name("c:quantification_q_value") == "q_value"
    assert ("q_value" in var, "c:q_value" in var, "v:q_value" in var) == (False, False, True)
    with pytest.raises(KeyError, match="'c:q_value'"):
        var["c:q_value"]
    with pytest.raises(KeyError, match="'c:q_value'"):
        var[["c:q_value"]]
    assert var[["v:q_value", "apb:peptidoform_ion"]].columns == ["q_value", "ProForma_ion"]


def test_a_plain_key_reads_the_catalog_where_it_answers_and_v_the_vendor() -> None:
    """AlphaDIA 1.12 reports its own ``decoy`` beside APB's ``apb_Decoy``, which the key names;
    its ``intensity`` is directLFQ's, which the abundance key ``intensity`` is not."""
    parsed = _result(
        "alphadia/v1_12/rules.json",
        ["qval", "intensity"],
        {"decoy": [0, 1], "apb_Decoy": [False, True]},
    )
    level = DataCatalog(parsed, "abundance_alpha", "apb_alpha").levels["peptidoform_ion"]
    assert (level.var.name("decoy"), level.var.name("apb:decoy")) == ("apb_Decoy", "apb_Decoy")
    assert level.var.name("v:decoy") == "decoy"
    assert level.layers.get("a:intensity") is None
    assert level.layers.name("v:intensity") == level.layers.name("intensity") == "intensity"
    unnamed = DataCatalog(parsed, "abundance_alpha").levels["peptidoform_ion"]
    assert unnamed.var.name("decoy") == "decoy", "without apb_alpha, decoy is the vendor's own"


def test_a_prefix_of_no_composed_set_or_a_qualified_vendor_name_is_refused() -> None:
    """A prefix names one of the composed sets, a key of that set; ``v:`` takes no qualifiers."""
    parsed = _result("sage/rules.json", ["Intensity"], {"q_value": [0.001, 0.002]})
    var = DataCatalog(parsed, "confidence_alpha").levels["peptidoform_ion"].var
    with pytest.raises(ValueError, match=r"unknown prefix 'a'.*\['c', 'v'\]"):
        var.get("a:intensity")
    with pytest.raises(ValueError, match="unknown key 'intensity'"):
        var.get("c:intensity")
    with pytest.raises(ValueError, match="takes no qualifiers"):
        var.get("v:q_value", stage="run")


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
    var = catalog.levels["peptidoform_ion"].var
    assert {"charge", "decoy", "group", "peptidoform"} <= var.keys()
    assert var.name("charge", origin="vendor") == "Precursor_Charge"
    assert var.name("peptidoform", origin="apb2") == "ProForma_peptidoform"
    assert var.get("peptidoform", origin="vendor") is None
    group = catalog.levels["peptidoform_ion"].var.get("group")
    assert group is not None
    assert group.to_list() == ["P1", "P1;P2"]
    assert catalog.description.used_by == ("apb-catalog tests",)


def test_a_later_producers_field_is_unknown_until_it_runs(toy_set: str) -> None:
    """A FASTA-based field never reads as absent before apb-fasta had a chance to write it."""
    catalog = DataCatalog(_result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION), toy_set)
    with pytest.raises(UnresolvedField, match=r"apb-fasta has not run.*apb-fasta verify-peptides"):
        catalog.levels["peptidoform_ion"].var.get("contaminant")


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
    flag = catalog.levels["peptidoform_ion"].var.get("contaminant")
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
        catalog.levels["peptidoform_ion"].var.get("contaminant")
    vendor = catalog.levels["peptidoform_ion"].var.get("contaminant", origin="vendor")
    fasta = catalog.levels["peptidoform_ion"].var.get("contaminant", origin="apb_fasta")
    assert vendor is not None and vendor.to_list() == [False, True]
    assert fasta is not None and fasta.to_list() == [True, False]


def test_a_vendor_without_its_own_flag_offers_none(toy_set: str) -> None:
    """DIA-NN marks no contaminants itself, so only apb-fasta can answer them."""
    catalog = DataCatalog(_result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION), toy_set)
    assert catalog.levels["peptidoform_ion"].var.get("contaminant", origin="vendor") is None


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
    catalog.levels["peptidoform_ion"].var.get("contaminant")
    snapshot = catalog.snapshot()
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)
    assert _stored(read_parsed_levels(target), toy_set) == snapshot


def test_an_unknown_catalogue_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown catalogue"):
        DataCatalog(_result(*MAXQUANT), "everything")


def test_an_unreviewed_level_raises() -> None:
    """Without a reviewed rule the catalogue cannot even claim absence."""
    with pytest.raises(UnresolvedField, match=r"unknown.*rule_json"):
        DataCatalog(_result(None, ["Intensity"]), "confidence_alpha").levels[
            "peptidoform_ion"
        ].layers.get("pep")


def test_an_unreviewed_software_version_is_unknown() -> None:
    """A software version no catalogue variant names answers unknown."""
    with pytest.raises(UnresolvedField, match="no source catalogue reviewed"):
        DataCatalog(_edited_maxquant(software_version_pattern="^99\\."), "confidence_alpha").levels[
            "peptidoform_ion"
        ].layers.get("pep")


def test_an_edited_rule_keeps_its_entries() -> None:
    """Levels bind by software and version, so editing a rule within a version changes nothing."""
    parsed = _edited_maxquant(file_version=-1)
    layers = DataCatalog(parsed, "confidence_alpha").levels["peptidoform_ion"].layers
    assert layers.name("pep") == "PEP"


def test_an_absent_level_is_not_in_levels() -> None:
    """A level the result lacks has no entry in ``levels``."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence_alpha")
    assert "peptide" not in catalog.levels
    assert list(catalog.levels) == ["peptidoform_ion"]


def test_an_unknown_key_is_rejected() -> None:
    """A misspelling raises through ``[...]`` and with qualifiers; ``get`` reads it as absent,
    as ``dict.get`` does."""
    layers = DataCatalog(_result(*MAXQUANT), "confidence_alpha").levels["peptidoform_ion"].layers
    with pytest.raises(KeyError, match="pepp"):
        layers["pepp"]
    assert layers.get("pepp") is None
    with pytest.raises(ValueError, match="unknown key 'pepp'"):
        layers.get("pepp", unit="minute")


def test_keys_lists_what_a_level_offers() -> None:
    """``keys`` says what a level holds at one location."""
    maxquant = DataCatalog(_result(*MAXQUANT), "confidence_alpha").levels["peptidoform_ion"]
    assert maxquant.layers.keys() == {"pep"}
    spectronaut = DataCatalog(_result(*SPECTRONAUT), "confidence_alpha").levels["peptidoform_ion"]
    assert spectronaut.layers.keys() == {"pep", "q_value"}
    dia_nn = DataCatalog(
        _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"]), "confidence_alpha"
    ).levels["peptidoform_ion"]
    assert dia_nn.layers.keys() == {"q_value"}
    assert dia_nn.var.keys() == set(), "apb_alpha's keys only when it is named"
    sage = _result("sage/rules.json", ["Intensity"], {"q_value": [0.001, 0.002]})
    sage_ion = DataCatalog(sage, "confidence_alpha", "apb_alpha").levels["peptidoform_ion"]
    assert sage_ion.var.keys() == {"peptidoform_ion", "quantification_q_value"}


def test_listing_keys_on_an_unreviewed_level() -> None:
    """An unreviewed level cannot say which keys it offers."""
    with pytest.raises(UnresolvedField, match="unknown"):
        DataCatalog(_result(None, ["Intensity"]), "confidence_alpha").levels[
            "peptidoform_ion"
        ].layers.keys()


def test_listing_keys_is_not_recorded_as_a_lookup() -> None:
    """Only lookups that return data enter the snapshot."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence_alpha")
    catalog.levels["peptidoform_ion"].layers.keys()
    assert catalog.snapshot().resolutions == ()


def test_fields_lists_what_the_result_holds() -> None:
    """One row per catalogued field of every composed set, readable without knowing the vendor."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence_alpha", "apb_alpha")
    fields = catalog.fields().filter(pl.col("present"))
    assert fields.select("set", "location", "name", "kind").rows() == [
        ("confidence_alpha", "layers", "PEP", "pep"),
        ("apb_alpha", "var", "ProForma_ion", "peptidoform_ion"),
    ]


def test_the_snapshot_records_its_catalogue_bindings_and_lookups() -> None:
    """Every lookup is kept for the persisted record."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence_alpha")
    catalog.levels["peptidoform_ion"].layers.get("pep")
    catalog.levels["peptidoform_ion"].layers.get("q_value")
    snapshot = catalog.snapshot()
    assert snapshot.catalogue == "confidence_alpha"
    assert [resolution.status for resolution in snapshot.resolutions] == ["resolved", "missing"]
    binding = snapshot.levels[0]
    assert isinstance(binding, ReviewedBinding)
    assert (binding.software_name, binding.software_version_pattern) == (
        "MaxQuant",
        "^(1\\.5|1\\.6|2\\.)",
    )
    unreviewed = DataCatalog(_result(None, ["Intensity"]), "confidence_alpha").snapshot()
    assert isinstance(unreviewed.levels[0], UnreviewedBinding)


def test_snapshots_of_two_catalogues_sit_side_by_side() -> None:
    """Attaching one set's snapshot keeps the other's, and the input stays unchanged."""
    parsed = _result(*MAXQUANT)
    confidence = DataCatalog(parsed, "confidence_alpha").snapshot()
    entrapment = DataCatalog(parsed, "proteobench_entrapment_alpha").snapshot()
    attached = attach_snapshot(attach_snapshot(parsed, confidence), entrapment)
    assert METADATA_KEY not in parsed.metadata
    assert _stored(attached, "confidence_alpha") == confidence
    assert _stored(attached, "proteobench_entrapment_alpha") == entrapment
    assert attached.levels["peptidoform_ion"].layers is parsed.levels["peptidoform_ion"].layers
    assert METADATA_KEY not in attached.levels["peptidoform_ion"].metadata, (
        "no request, no level summary"
    )


def _stored(parsed: ParsedLevels, catalogue: str) -> ResolutionSnapshot:
    """The snapshot ``attach_snapshot`` left, read from the metadata as a consumer reads it."""
    namespace = cast(dict[str, Any], parsed.metadata[METADATA_KEY])
    return ResolutionSnapshot.model_validate(namespace[catalogue]["result"])


def _with_namespace(parsed: ParsedLevels, namespace: JsonValue) -> ParsedLevels:
    return replace(parsed, metadata={**parsed.metadata, METADATA_KEY: namespace})


def test_attaching_keeps_unrelated_namespace_entries() -> None:
    """Attaching adds this catalogue's snapshot and leaves every other entry as it was."""
    parsed = _with_namespace(_result(*MAXQUANT), {"other": {"contract": "elsewhere"}})
    snapshot = DataCatalog(parsed, "confidence_alpha").snapshot()

    attached = attach_snapshot(parsed, snapshot)

    assert attached.metadata[METADATA_KEY] == {
        "other": {"contract": "elsewhere"},
        "confidence_alpha": {"result": snapshot.model_dump(mode="json")},
    }
    assert parsed.metadata[METADATA_KEY] == {"other": {"contract": "elsewhere"}}


@pytest.mark.parametrize("namespace", [["prior-evidence"], "prior-evidence", 3, None])
def test_a_malformed_namespace_raises_instead_of_being_replaced(namespace: JsonValue) -> None:
    """A present namespace that is not an object is never read as absent or overwritten."""
    parsed = _with_namespace(_result(*MAXQUANT), namespace)
    snapshot = DataCatalog(parsed, "confidence_alpha").snapshot()

    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        attach_snapshot(parsed, snapshot)
    assert parsed.metadata[METADATA_KEY] == namespace


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_a_stored_malformed_namespace_still_raises(tmp_path: Path, suffix: str) -> None:
    """Valid JSON of the wrong shape survives storage, so reading it back must still raise."""
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(_with_namespace(_result(*MAXQUANT), ["prior-evidence"]), target)
    restored = read_parsed_levels(target)
    snapshot = DataCatalog(restored, "confidence_alpha").snapshot()

    with pytest.raises(ValueError, match="not snapshots by catalogue"):
        attach_snapshot(restored, snapshot)
    assert restored.metadata[METADATA_KEY] == ["prior-evidence"]


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_snapshots_round_trip_every_storage_format(tmp_path: Path, suffix: str) -> None:
    """Stored snapshots read back identically and leave the scientific data untouched."""
    parsed = _result(*MAXQUANT)
    catalog = DataCatalog(parsed, "confidence_alpha")
    catalog.levels["peptidoform_ion"].layers.get("pep")
    snapshot = catalog.snapshot()
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)

    restored = read_parsed_levels(target)

    assert _stored(restored, "confidence_alpha") == snapshot
    for name, table in parsed.levels["peptidoform_ion"].layers.items():
        assert_frame_equal(restored.levels["peptidoform_ion"].layers[name].wide(), table.wide())


def test_a_stored_snapshot_is_readable_as_plain_json(tmp_path: Path) -> None:
    """Consumers can follow the contract with apb2 and the standard library alone."""
    parsed = _result(*MAXQUANT)
    catalog = DataCatalog(parsed, "confidence_alpha")
    catalog.levels["peptidoform_ion"].layers.get("pep")
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, catalog.snapshot()), target)

    namespace: dict[str, Any] = json.loads(
        json.dumps(read_parsed_levels(target).metadata["catalog"])
    )
    stored = namespace["confidence_alpha"]["result"]

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
    assert (entry["kind"], entry["qualifiers"]) == ("pep", {"stage": "identification"})


def test_every_packaged_set_states_its_purpose_and_users() -> None:
    """Each set with entries has a description, and each description entries."""
    text = resources.files("apb_catalog").joinpath("data", "catalog.csv").read_text("utf-8")
    described = {row["set"] for row in csv.DictReader(io.StringIO(text))}
    descriptions = packaged_descriptions()
    assert set(descriptions) == described
    assert all(d.purpose and d.used_by for d in descriptions.values())


def test_snapshot_embeds_the_set_description() -> None:
    """A snapshot reader learns what the set is for without the package."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence_alpha")
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
    catalog = DataCatalog(parsed, "proteobench_entrapment_alpha")
    assert catalog.levels["peptidoform_ion"].layers.keys() == {"q_value"}
    assert catalog.levels["peptidoform_ion"].var.keys() == {"library_q_value", "q_value"}
    found = catalog.levels["peptidoform_ion"].var.get("library_q_value")
    assert found is not None
    assert (found.name, found.to_list()) == ("Lib_Q_Value", library)
    experiment = catalog.levels["peptidoform_ion"].var.get("q_value")
    assert experiment is not None
    assert experiment.name == "Global_Q_Value"
    assert catalog.levels["peptidoform_ion"].layers.get("pep") is None, "PEP is not ranked by"
    maxquant = DataCatalog(_result(*MAXQUANT), "proteobench_entrapment_alpha")
    assert maxquant.levels["peptidoform_ion"].layers.keys() == set()


def test_abundance_finds_the_un_normalized_layer_where_one_exists() -> None:
    """DIA-NN writes its precursor quantity before and after normalization; PEAKS only after."""
    layers = ["Precursor_Normalised", "Precursor_Quantity", "Ms1_Area", "Ms1_Normalised"]
    parsed = _result("diann/v1_8/rules.json", layers)
    catalog = DataCatalog(parsed, "abundance_alpha")
    ion = catalog.levels["peptidoform_ion"].layers
    assert ion.name("intensity") == "Precursor_Quantity"
    assert ion.name("intensity_norm_settings") == "Precursor_Normalised"
    peaks = DataCatalog(_result("peaks/rules.json", ["Normalized_Area"]), "abundance_alpha")
    assert peaks.levels["peptidoform_ion"].layers.get("intensity") is None


def test_an_undocumented_normalization_has_its_own_key() -> None:
    """A layer nobody documented the normalization of is not offered as an un-normalized one:
    asking for that is unknown, and its own key finds it."""
    catalog = DataCatalog(_result("pb_custom/rules.json", ["Intensity"]), "abundance_alpha")
    layers = catalog.levels["peptidoform_ion"].layers
    assert layers.keys() == {"intensity_norm_unknown"}
    with pytest.raises(UnresolvedField, match="leaves normalization unknown"):
        layers.get("intensity")
    assert layers.name("intensity_norm_unknown") == "Intensity"


def test_a_qualifier_picks_one_of_the_fields_a_key_names() -> None:
    """DIA-NN 1.8's protein groups have two normalized intensities; the key alone is ambiguous,
    and aggregation tells them apart."""
    rule = ("diann/v1_8/rules.json", ["PG_Normalised", "PG_MaxLFQ"])
    layers = (
        DataCatalog(_result(*rule, level="protein"), "abundance_alpha").levels["protein"].layers
    )
    with pytest.raises(UnresolvedField, match="ambiguous"):
        layers.get("intensity_norm_settings")
    assert layers.name("intensity_norm_settings", aggregation="maxlfq") == "PG_MaxLFQ"
    assert layers.name("intensity_norm_settings", aggregation="top_n") == "PG_Normalised"


def test_a_key_fixes_its_kind_and_qualifiers() -> None:
    """The key names the normalization, so a qualifier keyword may not restate or contradict it."""
    catalog = DataCatalog(
        _result("diann/v1_8/rules.json", ["Precursor_Quantity"]), "abundance_alpha"
    )
    with pytest.raises(ValueError, match="intensity fixes normalization"):
        catalog.levels["peptidoform_ion"].layers.get("intensity", normalization="none")
    with pytest.raises(ValueError, match="fixes kind"):
        catalog.levels["peptidoform_ion"].layers.get("intensity_norm_settings", kind="intensity")


def test_each_level_counts_the_requests_its_snapshot_answered() -> None:
    """A level record says how many lookups resolved, were missing, or stayed unresolved."""
    catalog = DataCatalog(_result(*MAXQUANT), "confidence_alpha")
    catalog.levels["peptidoform_ion"].layers.get("pep")
    catalog.levels["peptidoform_ion"].layers.get("q_value")

    attached = attach_snapshot(_result(*MAXQUANT), catalog.snapshot())

    records = cast(dict[str, Any], attached.levels["peptidoform_ion"].metadata[METADATA_KEY])
    assert [
        (entry["name"], entry["value"], entry["status"])
        for entry in records["confidence_alpha"]["summary"]
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
    return parsed, DataCatalog(parsed, "abundance_alpha", "confidence_alpha")


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
    assert level.layers["intensity_norm_settings"] is level.X, "the primary layer is X"


def test_a_name_that_is_no_key_reads_the_levels_own_field() -> None:
    """As cf_xarray: a key first, then the level's own name, else KeyError."""
    parsed, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    assert level.layers["Q_Value"] is level.layers["q_value"]
    assert level.var["Precursor_Charge"].to_list() == [2, 3]
    named = DataCatalog(parsed, "abundance_alpha", "apb_alpha").levels["peptidoform_ion"]
    assert named.var["peptidoform_ion"].to_list() == ["PEPTIDE/2", "PEPTIDEK/3"], "apb's key"
    with pytest.raises(KeyError, match="nonsense"):
        level.layers["nonsense"]
    with pytest.raises(KeyError, match="Precursor_Normalised"):
        level.layers["Precursor_Normalised"]  # the primary layer is X, not one of the layers


def test_keys_and_in_know_the_catalogs_keys_only() -> None:
    """Vendor names are read but not listed, as cf_xarray's keys()."""
    _, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    assert level.layers.keys() == {"intensity", "intensity_norm_settings", "q_value"}
    assert "intensity" in level.layers
    assert "Q_Value" not in level.layers
    assert level.var.keys() == set()


def test_obs_and_var_names_join_the_key_columns() -> None:
    """One name per observation and variable, polars, not pandas."""
    _, catalog = _levels()
    level = catalog.levels["peptidoform_ion"]
    assert level.var_names.to_list() == ["PEPTIDE/2", "PEPTIDEK/3"]
    assert level.obs_names.dtype == pl.String
    assert level.obs_names.len() == level.X.shape[0]


def test_only_the_sets_named_are_composed() -> None:
    """``apb_alpha`` answers only when named; the first set named gives the default snapshot,
    and a catalog of no set reads the level's own names."""
    parsed, catalog = _levels()
    assert catalog.levels["peptidoform_ion"].var.get("peptidoform_ion") is None
    named = DataCatalog(parsed, "confidence_alpha", "apb_alpha")
    assert named.levels["peptidoform_ion"].var.get("peptidoform_ion") is not None
    assert catalog.snapshot().catalogue == "abundance_alpha", "the first set named"
    assert named.snapshot("apb_alpha").catalogue == "apb_alpha"
    with pytest.raises(KeyError, match="apb_alpha"):
        catalog.snapshot("apb_alpha")
    unnamed = DataCatalog(parsed)
    assert unnamed.levels["peptidoform_ion"].var["Precursor_Charge"].to_list() == [2, 3]
    with pytest.raises(ValueError, match="no catalogue set named"):
        unnamed.snapshot()


def test_an_apps_set_opens_once_the_app_has_run() -> None:
    """``fasta_peptides_alpha`` answers nothing before apb-fasta runs, so opening it says what to run;
    once it has run, every key listed reads, as AnnData's keys()."""
    unverified = _result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION)
    with pytest.raises(ValueError, match=r"apb-fasta has not run.*apb-fasta verify-peptides"):
        DataCatalog(unverified, "fasta_peptides_alpha")
    ran = _result(
        "diann/v2/rules.json",
        ["Ms1_Normalised"],
        DIANN_ION,
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    level = DataCatalog(ran, "fasta_peptides_alpha").levels["peptidoform_ion"]
    assert "fasta_matches_contaminant" in level.var
    assert level.var["fasta_matches_contaminant"].to_list() == [True, False]


def test_the_protein_set_opens_once_merge_annotations_has_run() -> None:
    """Each apb-fasta command fills its own set: peptide verification alone leaves
    ``fasta_proteins_alpha`` unable to answer, protein annotation opens it."""
    genes = {"fasta": pl.DataFrame({"fasta_gene_names": ["GENE1", "GENE2;GENE3"]})}
    verified = _result(
        "diann/v2/rules.json", ["PG_MaxLFQ"], level="protein", varm=genes, metadata=FASTA_RAN
    )
    with pytest.raises(ValueError, match=r"run `apb-fasta merge-annotations`"):
        DataCatalog(verified, "fasta_proteins_alpha")
    annotated = _result(
        "diann/v2/rules.json",
        ["PG_MaxLFQ"],
        level="protein",
        varm=genes,
        metadata={"fasta": {"provenance": {"protein_annotation": {}}}},
    )
    var = DataCatalog(annotated, "fasta_proteins_alpha").levels["protein"].var
    assert var.name("fasta_gene_names") == "fasta/fasta_gene_names"
    assert var["fasta_gene_names"].to_list() == ["GENE1", "GENE2;GENE3"]


def test_answering_sets_lists_the_sets_a_result_opens() -> None:
    """The sets whose app or annotation the result lacks are left out, without raising."""
    plain = _result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION)
    listed = DataCatalog.answering_sets(plain)
    assert "abundance_alpha" in listed
    assert not {"fasta_peptides_alpha", "fasta_proteins_alpha", "obs_annotation_alpha"} & set(
        listed
    )
    verified = _result("diann/v2/rules.json", ["Ms1_Normalised"], DIANN_ION, metadata=FASTA_RAN)
    listed = DataCatalog.answering_sets(verified)
    assert "fasta_peptides_alpha" in listed
    assert "fasta_proteins_alpha" not in listed
    for name in listed:
        DataCatalog(verified, name)


def test_a_list_of_names_reads_every_column_a_key_names(toy_set: str) -> None:
    """As cf_xarray: one key, two columns; the list reads both, a varm column as table/column."""
    parsed = _result(
        "fragpipe/rules.json",
        ["Intensity"],
        {"apb_Contaminant": [False, True]},
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    level = DataCatalog(parsed, toy_set).levels["peptidoform_ion"]
    with pytest.raises(UnresolvedField, match="ambiguous"):
        level.var["contaminant"]
    both = level.var[["contaminant", "ProForma_ion"]]
    assert both.columns == [
        "apb_Contaminant",
        "fasta_validation/fasta_matches_contaminant",
        "ProForma_ion",
    ]
    assert both.get_column("apb_Contaminant").to_list() == [False, True]
    with pytest.raises(KeyError, match="nonsense"):
        level.var[["contaminant", "nonsense"]]


def test_a_list_of_names_raises_while_a_producer_has_not_run(toy_set: str) -> None:
    """Before apb-fasta runs, the list cannot say which columns the key names."""
    parsed = _result("fragpipe/rules.json", ["Intensity"], {"apb_Contaminant": [False, True]})
    level = DataCatalog(parsed, toy_set).levels["peptidoform_ion"]
    with pytest.raises(UnresolvedField, match="apb-fasta has not run"):
        level.var[["contaminant"]]


def test_get_answers_none_where_a_name_reads_no_field() -> None:
    """``get`` returns ``None`` where ``[...]`` raises; ``name`` says which field a key reads."""
    _, catalog = _levels()
    layers = catalog.levels["peptidoform_ion"].layers
    assert layers.get("pep") is None, "a key the level has no field for"
    assert layers.get("nonsense") is None
    with pytest.raises(KeyError, match="pep"):
        layers["pep"]
    with pytest.raises(KeyError, match="pep"):
        layers.name("pep")
    assert layers.get("q_value") is layers["q_value"]
    assert layers.name("q_value") == "Q_Value"
    assert layers.name("Q_Value") == "Q_Value", "the level's own name"


def test_a_varm_fields_name_is_its_table_and_column() -> None:
    """``get`` reads the varm column, ``name`` names it."""
    ran = _result(
        "diann/v2/rules.json",
        ["Ms1_Normalised"],
        DIANN_ION,
        varm=FASTA_CONTAMINANTS,
        metadata=FASTA_RAN,
    )
    var = DataCatalog(ran, "fasta_peptides_alpha").levels["peptidoform_ion"].var
    assert var.name("fasta_matches_contaminant") == "fasta_validation/fasta_matches_contaminant"
    flag = var.get("fasta_matches_contaminant")
    assert flag is not None and flag.to_list() == [True, False]


def test_get_then_name_records_one_lookup() -> None:
    """The snapshot keeps each answer once, however often it is asked."""
    _, catalog = _levels()
    layers = catalog.levels["peptidoform_ion"].layers
    layers.get("q_value")
    layers.name("q_value")
    keys = [found.request.key for found in catalog.snapshot("confidence_alpha").resolutions]
    assert keys == ["q_value"]
