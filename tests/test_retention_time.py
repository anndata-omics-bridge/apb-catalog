"""Observed RT and its original units resolve without vendor names in consumers."""

from __future__ import annotations

import polars as pl
import pytest
from apb2.api import ParsedLevel, ParsedLevels
from polars.testing import assert_frame_equal

from apb_catalog.api import Catalog, DataCatalog, Reference, UnresolvedField
from tests.packaged_rules import declared_rule_json


@pytest.mark.parametrize(
    "software,version,column,unit",
    [
        ("DIA-NN", "1.7.16", "RT", "minute"),
        ("DIA-NN", "1.8.1", "RT", "minute"),
        ("DIA-NN", "2.3.0", "RT", "minute"),
        ("MaxQuant", "2.4.0.0", "Retention_Time", "minute"),
        ("AlphaDIA", "1.12.2", "RT_Observed", "second"),
        ("AlphaDIA", "2.1.0", "RT_Observed", "second"),
    ],
)
def test_reviewed_rt_names_and_units(software: str, version: str, column: str, unit: str) -> None:
    catalog = Catalog(software, version, "chromatography")
    assert catalog.layer("peptidoform_ion", kind="retention_time", unit=unit) == Reference(
        level="peptidoform_ion", location="layers", name=column
    )
    other = "second" if unit == "minute" else "minute"
    assert catalog.layer("peptidoform_ion", kind="retention_time", unit=other) is None
    assert catalog.layer("protein", kind="retention_time") is None


def _result(include_rt: bool) -> ParsedLevels:
    values = pl.DataFrame({"obs_0": [0.0, 10.0], "obs_1": [12.5, None]})
    layers = {"quantity": values}
    if include_rt:
        layers["RT"] = values
    level = ParsedLevel.build(
        obs=pl.DataFrame({"Run": ["A", "B"]}),
        obs_keys=["Run"],
        var=pl.DataFrame({"ProForma_ion": ["PEPTIDEK/2", "SECONDPEPK/2"]}),
        var_keys=["ProForma_ion"],
        var_roles={},
        primary_layer="quantity",
        abundance=layers,
        uns={
            "provenance": {
                "rule_json": declared_rule_json("diann/v1_8/rules.json", "peptidoform_ion")
            }
        },
    )
    return ParsedLevels(levels={"peptidoform_ion": level}, uns={})


def test_data_catalog_returns_original_values_without_converting() -> None:
    parsed = _result(True)
    catalog = DataCatalog(parsed, "chromatography")
    found = catalog.layer("peptidoform_ion", kind="retention_time", unit="minute")
    assert found is not None
    assert found is parsed.levels["peptidoform_ion"].layers["RT"]
    assert_frame_equal(found.wide(), parsed.levels["peptidoform_ion"].layers["RT"].wide())
    assert found.wide().row(0) == (0.0, 12.5), "zero RT and original minutes are preserved"
    snapshot = catalog.snapshot().model_dump(mode="json")
    assert snapshot["catalogue"] == "chromatography"


def test_rt_is_optional_in_a_reviewed_result() -> None:
    catalog = DataCatalog(_result(False), "chromatography")
    assert catalog.layer("peptidoform_ion", kind="retention_time", unit="minute") is None


def test_an_older_rule_without_retained_rt_answers_missing() -> None:
    catalog = Catalog("AlphaDIA", "1.10.0", "chromatography")
    assert catalog.layer("peptidoform_ion", kind="retention_time") is None


def test_feature_average_rt_is_distinct_from_per_run_rt() -> None:
    catalog = Catalog("MaxQuant", "2.4.0.0", "chromatography")
    assert catalog.var("peptidoform", kind="retention_time", unit="minute") == Reference(
        level="peptidoform", location="var", name="Retention_Time"
    )
    assert catalog.layer("peptidoform", kind="retention_time") is None


def test_instrument_dependent_units_are_not_assumed() -> None:
    catalog = Catalog("FragPipe", "22.0", "chromatography")
    assert catalog.layer("peptidoform_ion", kind="retention_time", unit="unknown") == Reference(
        level="peptidoform_ion", location="layers", name="Apex_Retention_Time"
    )
    with pytest.raises(UnresolvedField, match="unknown"):
        catalog.layer("peptidoform_ion", kind="retention_time", unit="second")
