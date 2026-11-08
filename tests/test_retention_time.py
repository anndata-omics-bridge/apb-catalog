"""RT fields of every kind and their original units resolve without vendor names."""

from __future__ import annotations

from typing import Literal

import polars as pl
import pytest
from apb2.api import ParsedLevel, ParsedLevels

from apb_catalog.api import Catalog, DataCatalog, UnresolvedField
from tests.packaged_rules import declared_rule_json


@pytest.mark.parametrize(
    "software,version,column,unit",
    [
        ("DIA-NN", "1.7.16", "RT", "minute"),
        ("DIA-NN", "1.8.1", "RT", "minute"),
        ("DIA-NN", "2.3.0", "RT", "minute"),
        ("MaxQuant", "2.4.0.0", "Retention_time", "minute"),
        ("AlphaDIA", "1.12.2", "rt_observed", "second"),
        ("AlphaDIA", "2.1.0", "precursor_rt_observed", "second"),
    ],
)
def test_reviewed_rt_names_and_units(software: str, version: str, column: str, unit: str) -> None:
    catalog = Catalog(software, version, "chromatography_alpha")
    assert catalog.levels["peptidoform_ion"].layers.get("retention_time", unit=unit) == column
    other = "second" if unit == "minute" else "minute"
    assert catalog.levels["peptidoform_ion"].layers.get("retention_time", unit=other) is None
    protein = catalog.levels.get("protein")
    assert protein is None or protein.layers.get("retention_time") is None


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
    catalog = DataCatalog(parsed, "chromatography_alpha")
    layers = catalog.levels["peptidoform_ion"].layers
    assert layers.name("retention_time", unit="minute") == "RT"
    found = layers.get("retention_time", unit="minute")
    assert found is not None
    assert found[:, 0].tolist() == [0.0, 12.5], "zero RT and original minutes are preserved"
    snapshot = catalog.snapshot().model_dump(mode="json")
    assert snapshot["catalogue"] == "chromatography_alpha"


def test_a_level_narrows_by_qualifiers_through_get_and_name() -> None:
    """``[...]`` takes no keywords; ``get`` and ``name`` take the qualifiers a key leaves open."""
    layers = DataCatalog(_result(True), "chromatography_alpha").levels["peptidoform_ion"].layers
    assert layers.name("retention_time", unit="minute") == "RT"
    assert layers.get("retention_time", unit="second") is None
    found = layers.get("retention_time", unit="minute")
    assert found is not None and found.shape == (2, 2)
    with pytest.raises(ValueError, match="unknown key 'RT'"):
        layers.get("RT", unit="minute")
    names = Catalog("DIA-NN", "2.3.0", "chromatography_alpha").levels["peptidoform_ion"].layers
    assert names.get("retention_time", unit="minute") == "RT"
    assert names.get("retention_time", unit="second") is None


def test_rt_is_optional_in_a_reviewed_result() -> None:
    catalog = DataCatalog(_result(False), "chromatography_alpha")
    assert catalog.levels["peptidoform_ion"].layers.get("retention_time", unit="minute") is None


def test_an_older_rule_without_retained_rt_answers_missing() -> None:
    catalog = Catalog("AlphaDIA", "1.10.0", "chromatography_alpha")
    assert catalog.levels["peptidoform_ion"].layers.get("retention_time") is None


def test_feature_average_rt_is_distinct_from_per_run_rt() -> None:
    catalog = Catalog("MaxQuant", "2.4.0.0", "chromatography_alpha")
    assert (
        catalog.levels["peptidoform"].var.get("retention_time", unit="minute") == "Retention_time"
    )
    assert catalog.levels["peptidoform"].layers.get("retention_time") is None


def test_instrument_dependent_units_are_not_assumed() -> None:
    catalog = Catalog("FragPipe", "22.0", "chromatography_alpha")
    assert (
        catalog.levels["peptidoform_ion"].layers.get("retention_time", unit="unknown")
        == "Apex_Retention_Time"
    )
    with pytest.raises(UnresolvedField, match="unknown"):
        catalog.levels["peptidoform_ion"].layers.get("retention_time", unit="second")


@pytest.mark.parametrize(
    "software,version,kind,location,column,unit",
    [
        ("DIA-NN", "2.3.0", "predicted_retention_time", "layers", "Predicted_RT", "minute"),
        ("DIA-NN", "2.3.0", "aligned_retention_time", "layers", "Predicted_iRT", "irt"),
        ("DIA-NN", "2.3.0", "library_retention_time", "var", "iRT", "irt"),
        ("Spectronaut", "19.9", "predicted_retention_time", "layers", "EG_RTPredicted", "minute"),
        ("Spectronaut", "19.9", "aligned_retention_time", "layers", "EG_iRTEmpirical", "irt"),
        ("Spectronaut", "19.9", "library_retention_time", "var", "EG_iRTPredicted", "irt"),
        (
            "MaxQuant",
            "2.4.0.0",
            "aligned_retention_time",
            "layers",
            "Calibrated_retention_time",
            "minute",
        ),
        (
            "AlphaDIA",
            "2.1.0",
            "predicted_retention_time",
            "layers",
            "precursor_rt_calibrated",
            "second",
        ),
        (
            "AlphaDIA",
            "2.1.0",
            "library_retention_time",
            "layers",
            "precursor_rt_library",
            "unknown",
        ),
        ("ProlineStudio", "2.3.0", "aligned_retention_time", "layers", "corrected_time", "minute"),
        (
            "ProlineStudio",
            "2.3.0",
            "aligned_retention_time",
            "var",
            "master_quant_peptide_ion_elution_time",
            "minute",
        ),
        ("ProlineStudio", "2.3.0", "retention_time", "var", "master_elution_time", "minute"),
    ],
)
def test_measured_aligned_predicted_and_library_rt_are_separate_kinds(
    software: str,
    version: str,
    kind: str,
    location: Literal["layers", "var"],
    column: str,
    unit: str,
) -> None:
    catalog = Catalog(software, version, "chromatography_alpha")
    level = catalog.levels["peptidoform_ion"]
    found = (level.layers if location == "layers" else level.var).get(kind, unit=unit)
    assert found == column


@pytest.mark.parametrize(
    "software,version,kind,column,unit",
    [
        ("DIA-NN", "2.3.0", "peak_start", "RT_Start", "minute"),
        ("DIA-NN", "2.3.0", "peak_end", "RT_Stop", "minute"),
        ("DIA-NN", "2.3.0", "peak_fwhm", "FWHM", "minute"),
        ("Spectronaut", "21.0", "peak_width", "EG_PeakWidth", "minute"),
        ("Spectronaut", "21.0", "aligned_peak_start", "EG_StartiRT", "irt"),
        ("Spectronaut", "21.0", "mean_apex_retention_time", "EG_MeanApexRT", "minute"),
        ("MaxQuant", "2.4.0.0", "aligned_peak_end", "Calibrated_retention_time_finish", "minute"),
        ("MaxQuant", "2.4.0.0", "peak_width", "Retention_length", "minute"),
        ("MetaMorpheus", "1.0.5", "ms2_retention_time", "MS2_Retention_Time", "minute"),
        ("MetaMorpheus", "1.0.5", "retention_time", "Peak_RT_Apex", "minute"),
        ("MetaMorpheus", "1.0.5", "peak_end", "Peak_RT_End", "minute"),
        ("AlphaDIA", "1.12.2", "peak_fwhm", "cycle_fwhm", "unknown"),
    ],
)
def test_peak_bounds_widths_and_scan_times_are_their_own_kinds(
    software: str, version: str, kind: str, column: str, unit: str
) -> None:
    layers = Catalog(software, version, "chromatography_alpha").levels["peptidoform_ion"].layers
    assert layers.get(kind, unit=unit) == column
