"""The pandas API: the catalog on the AnnData or MuData object APB2 wrote answers as the polars
one does on the same result, with AnnData's own values."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import anndata
import mudata
import numpy as np
import pandas as pd
import polars as pl
import pytest
from anndata import AnnData
from apb2.api import JsonValue, ParsedLevel, ParsedLevels, write_parsed_levels
from mudata import MuData
from scripts.build_bundle import synthetic_level

from apb_catalog import api, api_pandas
from apb_catalog.source import catalogue_set
from tests.packaged_rules import declared_rule_json

SETS = ("abundance_alpha", "confidence_alpha")
LEVEL = "peptidoform_ion"


def _parsed(*, fasta_ran: bool = True) -> ParsedLevels:
    """A DIA-NN ion level of three runs and two features, with a layer whose name AnnData cannot
    store as it is and an apb-fasta varm table."""
    runs = pl.DataFrame({"Run": ["R1", "R2", "R3"]})
    features = pl.DataFrame(
        {"ProForma_ion": ["A/2", "B/2"], "Global_Q_Value": [0.01, 0.02], "Genes": ["G1", "G2"]}
    )
    values = {
        name: pl.DataFrame({f"c{run}": [float(offset + run), 2.0 * run] for run in range(3)})
        for offset, name in enumerate(("Ms1_Normalised", "Q_Value", "a/b"))
    }
    level = ParsedLevel.build(
        runs,
        ("Run",),
        features,
        ("ProForma_ion",),
        {},
        primary_layer="Ms1_Normalised",
        abundance=values,
        uns={"provenance": {"rule_json": declared_rule_json("diann/v2/rules.json", LEVEL)}},
    )
    level = replace(
        level,
        varm={"fasta_validation": pl.DataFrame({"fasta_matches_contaminant": [True, False]})},
    )
    metadata: dict[str, JsonValue] = (
        {"fasta": {"provenance": {"peptide_verification": {}}}} if fasta_ran else {}
    )
    return ParsedLevels(levels={LEVEL: level}, uns={}, metadata=metadata)


def _stored(parsed: ParsedLevels, tmp_path: Path, suffix: str) -> MuData | AnnData:
    target = tmp_path / f"result.{suffix}"
    write_parsed_levels(parsed, target)
    return mudata.read_h5mu(target) if suffix == "h5mu" else anndata.read_h5ad(target)


def _plain(value: object) -> object:
    if isinstance(value, pl.Series):
        return value.to_list()
    if isinstance(value, pd.Series):
        return value.tolist()
    return np.asarray(value).tolist()


def _outcome(read: Callable[[str], object], key: str) -> object:
    try:
        value = read(key)
    except (LookupError, ValueError) as error:
        return type(error).__name__
    return None if value is None else _plain(value)


@pytest.mark.parametrize("suffix", ["h5mu", "h5ad"])
@pytest.mark.parametrize("fasta_ran", [True, False])
def test_every_key_answers_as_the_polars_catalog(
    tmp_path: Path, suffix: str, fasta_ran: bool
) -> None:
    """Same keys offered, same names, same values or errors, for every key of every set."""
    parsed = _parsed(fasta_ran=fasta_ran)
    polars = api.DataCatalog(parsed, *SETS).levels[LEVEL]
    pandas = api_pandas.DataCatalog(_stored(parsed, tmp_path, suffix), *SETS).levels[LEVEL]
    keys = sorted({key.key for name in (*SETS, "apb_alpha") for key in catalogue_set(name).keys})
    assert polars.layers.keys() == {"intensity_ms1_norm_settings", "q_value"}
    for location in ("layers", "var", "obs"):
        mine, theirs = getattr(pandas, location), getattr(polars, location)
        assert mine.keys() == theirs.keys()
        for key in keys:
            assert _outcome(mine.get, key) == _outcome(theirs.get, key), key
            assert _outcome(mine.name, key) == _outcome(theirs.name, key), key


@pytest.mark.parametrize("suffix", ["h5mu", "h5ad"])
def test_values_are_anndatas_own(tmp_path: Path, suffix: str) -> None:
    """Matrices as AnnData holds them, columns as pandas Series, a list as a pandas DataFrame."""
    stored = _stored(_parsed(), tmp_path, suffix)
    ion = api_pandas.DataCatalog(stored, *SETS, "apb_fasta_alpha").levels[LEVEL]
    adata = cast(AnnData, stored.mod[LEVEL]) if isinstance(stored, MuData) else stored
    assert ion.X is adata.X
    assert ion.layers["q_value"] is adata.layers["Q_Value"]
    assert ion.layers["a/b"] is adata.layers["a_b"], "APB2's name, AnnData's a_b"
    q_value = ion.var["q_value"]
    assert isinstance(q_value, pd.Series)
    assert q_value.tolist() == [0.01, 0.02]
    flag = ion.var.get("fasta_matches_contaminant")
    assert flag is not None and flag.tolist() == [True, False]
    assert ion.var.name("fasta_matches_contaminant") == "fasta_validation/fasta_matches_contaminant"
    both = ion.var[["q_value", "fasta_matches_contaminant"]]
    assert list(both.columns) == ["Global_Q_Value", "fasta_validation/fasta_matches_contaminant"]
    assert ion.obs_names.equals(adata.obs_names)
    assert ion.var_names.equals(adata.var_names)


def test_a_missing_name_answers_as_api_does(tmp_path: Path) -> None:
    ion = api_pandas.DataCatalog(_stored(_parsed(), tmp_path, "h5mu"), *SETS).levels[LEVEL]
    with pytest.raises(KeyError, match="no key or field 'intensities'"):
        ion.layers["intensities"]
    assert ion.layers.get("intensities") is None


def test_an_object_apb2_did_not_write_is_rejected() -> None:
    with pytest.raises(ValueError, match="APB2 did not write this object"):
        api_pandas.DataCatalog(AnnData(np.ones((2, 2))), "abundance_alpha")


# Conversion: a new object of the catalogued fields alone, each under its key -----------------

KEYED_PROTEIN = {"protein": synthetic_level("diann/v1_8/rules.json", "protein")}


def _diann_protein(tmp_path: Path) -> MuData:
    """A synthetic DIA-NN 1.8 protein level: its two ``intensity_norm_settings`` layers differ
    in aggregation only, and ``Protein_Group`` is both ``protein_assignment`` and
    ``fasta_accessions``."""
    return cast(MuData, _stored(ParsedLevels(levels=KEYED_PROTEIN, uns={}), tmp_path, "h5mu"))


def test_a_level_converts_to_its_catalogued_fields_under_their_keys(tmp_path: Path) -> None:
    stored = _diann_protein(tmp_path)
    source = cast(AnnData, stored.mod["protein"])
    layers_before = list(source.layers)
    keyed = api_pandas.DataCatalog(stored, *SETS, "apb_alpha").levels["protein"].as_anndata()
    assert list(keyed.layers) == [
        "intensity",
        "intensity_norm_settings[aggregation=top_n]",
        "intensity_norm_settings[aggregation=maxlfq]",
        "q_value",
    ]
    assert list(keyed.var.columns) == [
        "library_q_value",
        "q_value",
        "decoy",
        "contaminant",
        "protein_assignment",
        "fasta_accessions",
    ]
    assert keyed.X is None, "no set says which layer is primary"
    assert keyed.obs_names.equals(source.obs_names)
    assert keyed.var_names.equals(source.var_names)
    maxlfq = np.asarray(keyed.layers["intensity_norm_settings[aggregation=maxlfq]"])
    assert np.array_equal(maxlfq, np.asarray(source.X)), "PG_MaxLFQ is the level's primary layer"
    groups = source.var["Protein_Group"].tolist()
    assert keyed.var["protein_assignment"].tolist() == groups
    assert keyed.var["fasta_accessions"].tolist() == groups
    record = keyed.uns["catalog"]
    assert record["sets"] == [*SETS, "apb_alpha"]
    assert record["layers"]["intensity_norm_settings[aggregation=maxlfq]"] == {
        "set": "abundance_alpha",
        "key": "intensity_norm_settings",
        "qualifiers": {"normalization": "run_setting", "aggregation": "maxlfq", "ms_level": "ms2"},
        "location": "layers",
        "name": "PG_MaxLFQ",
    }
    assert record["absent"] == {}
    assert set(record["source"]) == set(source.uns["apb"])
    assert list(source.layers) == layers_before
    assert "catalog" not in source.uns and "catalog" not in stored.uns


def test_the_abundance_set_alone_converts_to_layers_only(tmp_path: Path) -> None:
    """No set is composed unless named: the abundance set's keys are all layers, so the run and
    feature names are all obs and var keep."""
    stored = _diann_protein(tmp_path)
    keyed = api_pandas.DataCatalog(stored, "abundance_alpha").as_mudata()
    protein = cast(AnnData, keyed.mod["protein"])
    assert list(protein.layers) == [
        "intensity",
        "intensity_norm_settings[aggregation=top_n]",
        "intensity_norm_settings[aggregation=maxlfq]",
    ]
    assert list(protein.var.columns) == []
    assert list(protein.obs.columns) == []
    assert protein.var_names.equals(cast(AnnData, stored.mod["protein"]).var_names)
    assert list(keyed.uns["catalog"]["sets"]) == ["abundance_alpha"]


def test_the_converted_mudata_writes_and_reads_back(tmp_path: Path) -> None:
    keyed = api_pandas.DataCatalog(_diann_protein(tmp_path), *SETS).as_mudata()
    target = tmp_path / "keyed.h5mu"
    keyed.write_h5mu(target)
    back = mudata.read_h5mu(target)
    protein, written = cast(AnnData, back.mod["protein"]), cast(AnnData, keyed.mod["protein"])
    names = set(written.layers.keys())
    assert set(protein.layers.keys()) == names
    for name in names:
        mine, theirs = np.asarray(protein.layers[name]), np.asarray(written.layers[name])
        assert np.array_equal(mine, theirs, equal_nan=True), name
    assert cast(pd.DataFrame, protein.var).equals(cast(pd.DataFrame, written.var))
    assert protein.uns["catalog"]["layers"]["intensity"]["name"] == "PG_Quantity"
    assert list(back.uns["catalog"]["sets"]) == list(SETS)
    assert set(back.uns["catalog"]["source"]) == set(keyed.uns["catalog"]["source"])


def test_absent_keys_are_recorded_and_a_varm_field_becomes_a_var_column(tmp_path: Path) -> None:
    keyed = (
        api_pandas.DataCatalog(
            _stored(_parsed(), tmp_path, "h5ad"), *SETS, "apb_alpha", "apb_fasta_alpha"
        )
        .levels[LEVEL]
        .as_anndata()
    )
    assert list(keyed.layers) == ["intensity_ms1_norm_settings", "q_value"]
    assert list(keyed.var.columns) == ["q_value", "peptidoform_ion", "fasta_matches_contaminant"]
    assert keyed.var["fasta_matches_contaminant"].tolist() == [True, False]
    record = keyed.uns["catalog"]
    assert record["var"]["fasta_matches_contaminant"]["location"] == "varm"
    assert record["var"]["fasta_matches_contaminant"]["name"] == (
        "fasta_validation/fasta_matches_contaminant"
    )
    assert record["absent"] == {
        "layers": {"intensity": "recommended"},
        "var": {
            "peptide": "required",
            "peptidoform": "required",
            "decoy": "required",
            "contaminant": "required",
            "protein_assignment": "recommended",
        },
    }


def test_sdrf_factors_one_key_names_are_told_apart_by_their_own_names(tmp_path: Path) -> None:
    """Every SDRF factor column is ``group``; no qualifier tells them apart, so each column
    carries its own name, and the obs columns keep the runs' names."""
    factors = {"factor_value_treatment": ["a", "b"], "factor_value_dose": ["1", "2"]}
    level = synthetic_level("diann/v2/rules.json", LEVEL, obs_extra=factors)
    parsed = ParsedLevels(levels={LEVEL: level}, uns={}, metadata={"sdrf": {}})
    stored = cast(MuData, _stored(parsed, tmp_path, "h5mu"))
    catalog = api_pandas.DataCatalog(stored, "abundance_alpha", "obs_annotation_alpha")
    keyed = catalog.levels[LEVEL].as_anndata()
    assert list(keyed.obs.columns) == [
        "group[field=factor_value_treatment]",
        "group[field=factor_value_dose]",
    ]
    assert keyed.obs["group[field=factor_value_dose]"].tolist() == ["1", "2"]
    assert keyed.obs_names.equals(cast(AnnData, stored.mod[LEVEL]).obs_names)
    record = keyed.uns["catalog"]["obs"]["group[field=factor_value_treatment]"]
    assert (record["key"], record["name"]) == ("group", "factor_value_treatment")
