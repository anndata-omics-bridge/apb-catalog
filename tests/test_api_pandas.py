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

from apb_catalog import api, api_pandas
from apb_catalog.source import catalogue_set
from tests.packaged_rules import declared_rule_json

SETS = ("abundance", "confidence")
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
    keys = sorted({key.key for name in (*SETS, "apb") for key in catalogue_set(name).keys})
    assert polars.layers.keys() == {"normalized_ms1_intensity", "q_value"}
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
    ion = api_pandas.DataCatalog(stored, *SETS).levels[LEVEL]
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
        api_pandas.DataCatalog(AnnData(np.ones((2, 2))), "abundance")
