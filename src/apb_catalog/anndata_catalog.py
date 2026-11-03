"""A catalog on the AnnData or MuData object APB2 wrote, answering with AnnData's own values.

``DataCatalog(mdata, "abundance").levels["protein"].layers["maxlfq"]`` is the matrix AnnData
holds, runs by features; ``var`` and ``obs`` columns are pandas Series, and a list of names reads
a pandas DataFrame. Keys answer the same fields as :class:`apb_catalog.catalog.DataCatalog` on
the same result: the lookup is shared, only the values come from AnnData. A level's own names are
APB2's, which its ``uns["apb"]`` maps to the names AnnData stores, such as ``a/b`` to ``a_b``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

import pandas as pd
from anndata import AnnData
from apb2.api import JsonValue, UnsJsonCodec
from mudata import MuData

from apb_catalog.catalog import ComposedSets, Enforce, LevelFields, stored_rule_version
from apb_catalog.levels import Columns, Lookup, Slot
from apb_catalog.rules import Address
from apb_catalog.source import Reference

NAMESPACE = "apb"
"""The ``uns`` key under which APB2 stores its metadata and storage descriptor."""

_ROOT_TABLES = ("parse", "annotation_tables", "feature_relations")
"""Root ``uns["apb"]`` sections that are no result metadata, as APB2's readers leave them out."""


class StoredLevel:
    """One level APB2 stored in an AnnData object: where each field sits, and what a catalog
    binds the level by."""

    __slots__ = ("adata", "fields", "layers", "primary", "varm")

    def __init__(self, adata: AnnData, namespace: Mapping[str, object]) -> None:
        codec = UnsJsonCodec()
        storage = codec.storage(namespace)
        parse = codec.decode(namespace, storage).get("parse")
        layers = cast(list[dict[str, str]], storage["layers"])
        varm = cast(list[dict[str, Any]], storage["varm"])
        obs = cast(list[str], cast(dict[str, Any], storage["obs"])["columns"])
        var = cast(list[str], cast(dict[str, Any], storage["var"])["columns"])
        self.adata = adata
        self.primary = next(layer["name"] for layer in layers if layer["location"] == "X")
        self.layers = {
            layer["name"]: layer["physical_name"] for layer in layers if layer["location"] != "X"
        }
        self.varm = {str(table["name"]): str(table["physical_name"]) for table in varm}
        retained: set[Address] = {("layers", None, layer["name"]) for layer in layers}
        retained |= {("var", None, column) for column in var}
        retained |= {("obs", None, column) for column in obs}
        retained |= {
            ("varm", str(table["name"]), str(column))
            for table in varm
            for column in cast(list[str], table["columns"])
        }
        self.fields = LevelFields(
            stored_rule_version(cast(dict[str, JsonValue], parse))
            if isinstance(parse, dict)
            else None,
            frozenset(retained),
            tuple(obs),
        )


class AnnDataLevel:
    """One level of an AnnData or MuData object, with AnnData's slots read by key: ``X``,
    ``layers``, ``var``, ``obs``, ``obs_names`` and ``var_names``.

    As :class:`apb_catalog.levels.Level`, with AnnData's values: ``X`` and the layers as AnnData
    holds them, runs by features; ``var`` and ``obs`` columns as pandas Series.
    """

    __slots__ = ("_stored", "layers", "name", "obs", "var")

    def __init__(self, name: str, stored: StoredLevel, lookup: Lookup) -> None:
        self.name = name
        self._stored = stored
        self.layers = Slot(name, "layers", lookup, self._layer, set(stored.layers))
        self.var = Columns(name, "var", lookup, self._var, set(stored.adata.var.columns), _frame)
        self.obs = Columns(name, "obs", lookup, self._obs, set(stored.adata.obs.columns), _frame)

    @property
    def X(self) -> Any:  # noqa: ANN401 - AnnData's own type: numpy, sparse or dask
        """The primary layer, runs by features, as AnnData holds it."""
        return self._stored.adata.X

    @property
    def obs_names(self) -> pd.Index[str]:
        """AnnData's own run names."""
        return self._stored.adata.obs_names

    @property
    def var_names(self) -> pd.Index[str]:
        """AnnData's own feature names."""
        return self._stored.adata.var_names

    def _layer(self, reference: Reference) -> Any:  # noqa: ANN401 - as X
        name = reference.address()[2]
        if name == self._stored.primary:
            return self._stored.adata.X
        return self._stored.adata.layers[self._stored.layers[name]]

    def _var(self, reference: Reference) -> pd.Series[Any]:
        name = reference.address()[2]
        if reference.table is None:
            return self._stored.adata.var[name]
        # APB2 stores each varm table as a DataFrame aligned to var.
        table = cast(pd.DataFrame, self._stored.adata.varm[self._stored.varm[reference.table]])
        return table[name]

    def _obs(self, reference: Reference) -> pd.Series[Any]:
        return self._stored.adata.obs[reference.address()[2]]


class DataCatalog:
    """:class:`apb_catalog.catalog.DataCatalog` on the AnnData or MuData object APB2 wrote: the
    same keys answer the same fields, with AnnData's own values.

    ``DataCatalog(mdata, "abundance", "confidence").levels["peptidoform_ion"].layers["pep"]`` is
    the PEP matrix AnnData holds; ``var["q_value"]`` a pandas Series. A MuData's levels are its
    modalities; an h5ad's one level is the AnnData itself.

    Raises:
        ValueError: The object holds no ``uns["apb"]``, so APB2 did not write it.
    """

    __slots__ = ("levels",)

    def __init__(self, data: MuData | AnnData, *catalogs: str, enforce: Enforce = None) -> None:
        codec = UnsJsonCodec()
        namespace = _namespace(data.uns)
        storage = codec.storage(namespace)
        metadata = {
            key: value
            for key, value in codec.decode(namespace, storage).items()
            if key not in _ROOT_TABLES
        }
        entries = cast(list[dict[str, str]], storage["levels"])
        stored = {entry["name"]: _stored(data, entry["physical_name"]) for entry in entries}
        sets = ComposedSets(
            {name: level.fields for name, level in stored.items()}, metadata, catalogs, enforce
        )
        lookup = sets.lookup()
        self.levels = {name: AnnDataLevel(name, level, lookup) for name, level in stored.items()}


def _stored(data: MuData | AnnData, physical_name: str) -> StoredLevel:
    """A MuData holds each level as a modality; an h5ad keeps its one level's part under
    ``uns[level]``."""
    if isinstance(data, MuData):
        # APB2 writes every level as an AnnData modality, never a nested MuData.
        modality = cast(AnnData, data.mod[physical_name])
        return StoredLevel(modality, _namespace(modality.uns))
    return StoredLevel(data, _namespace(cast(Mapping[str, object], data.uns[physical_name])))


def _namespace(uns: Mapping[str, object]) -> Mapping[str, object]:
    found = uns.get(NAMESPACE)
    if not isinstance(found, Mapping):
        raise ValueError(f"no uns[{NAMESPACE!r}]: APB2 did not write this object")
    return cast(Mapping[str, object], found)


def _frame(columns: Sequence[tuple[str, pd.Series[Any]]]) -> pd.DataFrame:
    return pd.DataFrame(dict(columns))
