"""Callers ask a result for a meaning and get the data; snapshots survive every format."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from apb2.result_facade import (
    FinalLayerTable,
    JsonValue,
    ObsFinal,
    ParsedLevel,
    ParsedLevels,
    VarFinal,
    observation_labels,
    read_parsed_levels,
    write_parsed_levels,
)
from polars.testing import assert_frame_equal

from apb_catalog.catalog import (
    METADATA_KEY,
    Catalog,
    attach_snapshot,
    stale_levels,
    stored_snapshot,
)
from apb_catalog.resolver import ReviewedBinding, UnresolvedField, UnreviewedBinding
from tests.packaged_rules import declared_rule_json


def _ion_level(
    rule_json: str | None, layers: Sequence[str], var: Mapping[str, list[float]] | None = None
) -> ParsedLevel:
    obs = pl.DataFrame({"Run": ["R1", "R2", "R3"]})
    features = pl.DataFrame({"ProForma_ion": ["PEPTIDE/2", "PEPTIDER/3"], **(var or {})})
    labels = observation_labels(obs.height, reserved=features.columns)
    tables = {
        name: FinalLayerTable(
            layer_name=name,
            var_key_columns=("ProForma_ion",),
            values=features.select("ProForma_ion").with_columns(
                pl.lit(float(offset + 1) / 10 + column).alias(label)
                for column, label in enumerate(labels)
            ),
        )
        for offset, name in enumerate(layers)
    }
    uns: dict[str, JsonValue] = {"produced_by": "apb2", "quantification_level": "ion"}
    if rule_json is not None:
        uns["rule_json"] = rule_json
    return ParsedLevel(
        obs=ObsFinal(frame=obs, key_columns=("Run",)),
        var=VarFinal(frame=features, key_columns=("ProForma_ion",)),
        primary_layer_name=layers[0],
        uns=uns,
        layers=tables,
        obsm={},
        varm={},
        obsp={},
        varp={},
    )


def _result(
    rule: str | None, layers: Sequence[str], var: Mapping[str, list[float]] | None = None
) -> ParsedLevels:
    rule_json = declared_rule_json(rule, "ion") if rule is not None else None
    return ParsedLevels(levels={"ion": _ion_level(rule_json, layers, var)}, uns={})


MAXQUANT = ("maxquant/rules.json", ["Intensity", "PEP", "Score"])
SPECTRONAUT = (
    "spectronaut/rules.json",
    ["FG_Quantity", "EG_PEP", "EG_Qvalue", "FG_Qvalue", "EG_MaxChannelQvalue"],
)


def test_the_same_call_returns_each_vendors_layer() -> None:
    """Callers never name ``PEP`` or ``EG_PEP``; the catalogue does."""
    maxquant = _result(*MAXQUANT)
    spectronaut = _result(*SPECTRONAUT)
    assert (
        Catalog(maxquant).layer("ion", concept="confidence", kind="pep")
        is maxquant.levels["ion"].layers["PEP"]
    )
    assert (
        Catalog(spectronaut).layer("ion", concept="confidence", kind="pep")
        is spectronaut.levels["ion"].layers["EG_PEP"]
    )


def test_a_vendor_without_the_field_returns_none() -> None:
    """DIA-NN without its PEP layer is a reviewed absence, not an error."""
    parsed = _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"])
    catalog = Catalog(parsed)
    assert catalog.layer("ion", concept="confidence", kind="pep") is None
    assert (
        catalog.layer("ion", concept="confidence", kind="q_value")
        is parsed.levels["ion"].layers["Q_Value"]
    )


def test_two_equally_good_fields_raise_with_the_candidates() -> None:
    """Spectronaut's EG and FG q-values are both per-run precursor values; none is chosen."""
    with pytest.raises(UnresolvedField, match=r"ambiguous.*EG_Qvalue, FG_Qvalue"):
        Catalog(_result(*SPECTRONAUT)).layer("ion", concept="confidence", kind="q_value")


def test_keywords_select_a_non_default_variant() -> None:
    """The channel maximum is found only when asked for."""
    parsed = _result(*SPECTRONAUT)
    found = Catalog(parsed).layer("ion", concept="confidence", kind="q_value", statistic="max")
    assert found is parsed.levels["ion"].layers["EG_MaxChannelQvalue"]


def test_var_returns_the_per_feature_column() -> None:
    """Spectronaut's run-averaged precursor q-value is one value per feature."""
    parsed = _result(*SPECTRONAUT, {"EG_AvgProfileQvalue": [0.001, 0.002]})
    catalog = Catalog(parsed)
    assert catalog.var("ion", concept="confidence", kind="q_value") is None
    column = catalog.var("ion", concept="confidence", kind="q_value", statistic="mean")
    assert column is not None
    assert column.to_list() == [0.001, 0.002]


def test_an_unreviewed_level_raises() -> None:
    """Without a reviewed rule the catalogue cannot even claim absence."""
    with pytest.raises(UnresolvedField, match=r"unknown.*rule_json"):
        Catalog(_result(None, ["Intensity"])).layer("ion", concept="confidence", kind="pep")


def test_a_changed_rule_is_unreviewed() -> None:
    """A rule APB2 changed after review answers unknown until it is re-reviewed."""
    edited = json.loads(declared_rule_json("maxquant/rules.json", "ion"))
    edited["file_version"] = -1
    parsed = ParsedLevels(levels={"ion": _ion_level(json.dumps(edited), ["Intensity"])}, uns={})
    with pytest.raises(UnresolvedField, match="no source catalogue reviewed"):
        Catalog(parsed).layer("ion", concept="confidence", kind="pep")


def test_an_absent_level_returns_none() -> None:
    """Asking about a level the result lacks is answered, not raised."""
    assert Catalog(_result(*MAXQUANT)).layer("peptide", concept="confidence", kind="pep") is None


def test_an_unknown_kind_is_rejected() -> None:
    """A misspelled kind fails loudly instead of matching nothing."""
    with pytest.raises(ValueError, match="does not admit"):
        Catalog(_result(*MAXQUANT)).layer("ion", concept="confidence", kind="pepp")


def test_fields_lists_what_the_result_holds() -> None:
    """One row per catalogued field, readable without knowing the vendor."""
    fields = Catalog(_result(*MAXQUANT)).fields()
    assert fields.select("location", "name", "kind").rows() == [
        ("layers", "PEP", "pep"),
        ("layers", "Score", "score"),
    ]


def test_the_snapshot_records_bindings_and_lookups() -> None:
    """Every lookup is kept for the persisted record."""
    catalog = Catalog(_result(*MAXQUANT))
    catalog.layer("ion", concept="confidence", kind="pep")
    catalog.layer("ion", concept="confidence", kind="q_value")
    snapshot = catalog.snapshot()
    assert [resolution.status for resolution in snapshot.resolutions] == ["resolved", "missing"]
    binding = snapshot.levels[0]
    assert isinstance(binding, ReviewedBinding)
    assert (binding.software_name, binding.rule) == ("MaxQuant", "maxquant/rules.json")
    assert isinstance(Catalog(_result(None, ["Intensity"])).snapshot().levels[0], UnreviewedBinding)


def test_attaching_returns_a_new_result_and_leaves_the_input_unchanged() -> None:
    """Lookups are read-only and attachment is explicit."""
    parsed = _result(*MAXQUANT)
    attached = attach_snapshot(parsed, Catalog(parsed).snapshot())
    assert METADATA_KEY not in parsed.metadata
    assert stored_snapshot(parsed) is None
    assert attached.levels is parsed.levels


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_snapshots_round_trip_every_storage_format(tmp_path: Path, suffix: str) -> None:
    """Stored snapshots read back identically and leave the scientific data untouched."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed)
    catalog.layer("ion", concept="confidence", kind="pep")
    snapshot = catalog.snapshot()
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)

    restored = read_parsed_levels(target)

    assert stored_snapshot(restored) == snapshot
    assert stale_levels(restored, snapshot) == ()
    for name, table in parsed.levels["ion"].layers.items():
        assert_frame_equal(restored.levels["ion"].layers[name].values, table.values)


def test_a_stored_snapshot_is_readable_as_plain_json(tmp_path: Path) -> None:
    """Consumers can follow the contract with apb2 and the standard library alone."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed)
    catalog.layer("ion", concept="confidence", kind="pep")
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, catalog.snapshot()), target)

    stored: dict[str, Any] = json.loads(json.dumps(read_parsed_levels(target).metadata["catalog"]))

    assert stored["contract"] == "apb-catalog-resolution"
    answer = stored["resolutions"][0]
    assert answer["status"] == "resolved"
    assert answer["reference"] == {"level": "ion", "location": "layers", "name": "PEP"}
    entry = next(entry for entry in stored["entries"] if entry["reference"] == answer["reference"])
    assert entry["qualifiers"]["kind"] == "pep"


def test_a_changed_rule_makes_the_snapshot_stale() -> None:
    """Snapshots record the effective rule they were resolved against."""
    snapshot = Catalog(_result(*MAXQUANT)).snapshot()
    edited = json.loads(declared_rule_json("maxquant/rules.json", "ion"))
    edited["file_version"] = -1
    changed = ParsedLevels(levels={"ion": _ion_level(json.dumps(edited), ["Intensity"])}, uns={})
    assert stale_levels(changed, snapshot) == ("ion",)
    assert stale_levels(ParsedLevels(levels={}, uns={}), snapshot) == ("ion",)


def test_leaving_out_kind_lists_the_kinds_on_offer() -> None:
    """Without ``kind`` the catalogue says what a level holds for the concept."""
    assert Catalog(_result(*MAXQUANT)).layer("ion", concept="confidence") == ("pep", "score")
    assert Catalog(_result(*SPECTRONAUT)).layer("ion", concept="confidence") == ("pep", "q_value")
    dia_nn = _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"])
    assert Catalog(dia_nn).layer("ion", concept="confidence") == ("q_value",)
    assert Catalog(dia_nn).var("ion", concept="confidence") is None


def test_listing_kinds_on_an_absent_or_unreviewed_level() -> None:
    """An absent level offers nothing; an unreviewed one cannot say."""
    assert Catalog(_result(*MAXQUANT)).layer("peptide", concept="confidence") is None
    with pytest.raises(UnresolvedField, match="unknown"):
        Catalog(_result(None, ["Intensity"])).layer("ion", concept="confidence")


def test_listing_kinds_is_not_recorded_as_a_lookup() -> None:
    """Only lookups that return data enter the snapshot."""
    catalog = Catalog(_result(*MAXQUANT))
    catalog.layer("ion", concept="confidence")
    assert catalog.snapshot().resolutions == ()


def test_an_unknown_concept_is_rejected() -> None:
    """A concept the vocabulary does not declare fails loudly."""
    with pytest.raises(ValueError, match="unknown concept"):
        Catalog(_result(*MAXQUANT)).layer("ion", concept="abundance", kind="raw")
