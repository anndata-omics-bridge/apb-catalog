"""A catalog on the AnnData or MuData object APB2 wrote, answering with AnnData's own values.

``DataCatalog(mdata, "abundance_alpha").levels["protein"].layers["intensity"]`` is the matrix AnnData
holds, runs by features; ``var`` and ``obs`` columns are pandas Series, and a list of names reads
a pandas DataFrame. Keys answer the same fields as :class:`apb_catalog.catalog.DataCatalog` on
the same result: the lookup is shared, only the values come from AnnData. A level's own names are
APB2's, which its ``uns["apb"]`` maps to the names AnnData stores, such as ``a/b`` to ``a_b``.

``levels["protein"].as_anndata()`` and ``as_mudata()`` convert: a new object holding only the
catalogued fields, each under its key, which ``write_h5ad`` or ``write_h5mu`` writes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

import pandas as pd
from anndata import AnnData
from apb2.api import JsonValue, UnsJsonCodec
from mudata import MuData

from apb_catalog.catalog import ComposedSets, Enforce, LevelFields, stored_rule_version
from apb_catalog.levels import Columns, Lookup, Slot, field_name
from apb_catalog.rules import Address
from apb_catalog.source import Reference, SourceEntry

NAMESPACE = "apb"
"""The ``uns`` key under which APB2 stores its metadata and storage descriptor."""

CATALOG = "catalog"
"""The ``uns`` key of the record a conversion writes: what each column is, what is absent."""

type Written = Literal["layers", "var", "obs"]
"""The slots a conversion writes; a ``varm`` field becomes a ``var`` column."""

_WRITTEN: tuple[Written, ...] = ("layers", "var", "obs")

_ROOT_TABLES = ("parse", "annotation_tables", "feature_relations")
"""Root ``uns["apb"]`` sections that are no result metadata, as APB2's readers leave them out."""


class StoredLevel:
    """One level APB2 stored in an AnnData object: where each field sits, and what a catalog
    binds the level by."""

    __slots__ = ("adata", "fields", "layers", "namespace", "primary", "varm")

    def __init__(self, adata: AnnData, namespace: Mapping[str, object]) -> None:
        codec = UnsJsonCodec()
        storage = codec.storage(namespace)
        parse = codec.decode(namespace, storage).get("parse")
        layers = cast(list[dict[str, str]], storage["layers"])
        varm = cast(list[dict[str, Any]], storage["varm"])
        obs = cast(list[str], cast(dict[str, Any], storage["obs"])["columns"])
        var = cast(list[str], cast(dict[str, Any], storage["var"])["columns"])
        self.adata = adata
        self.namespace = namespace
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

    __slots__ = ("_sets", "_stored", "layers", "name", "obs", "var")

    def __init__(self, name: str, stored: StoredLevel, lookup: Lookup, sets: ComposedSets) -> None:
        self.name = name
        self._stored = stored
        self._sets = sets
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

    def as_anndata(self) -> AnnData:
        """The level's catalogued fields alone, each under its key, as a new AnnData.

        ``layers``, ``var`` and ``obs`` keep the level's run and feature names; ``X`` is empty,
        since no set says which layer is primary. A key that names several fields in one slot
        names each with the qualifiers that tell them apart, such as
        ``intensity_norm_settings[aggregation=maxlfq]``; a field two keys name is written under
        both. ``uns["catalog"]`` records, per slot, each column's set, key, qualifiers and the
        level's own name for it; under ``absent``, the required and recommended keys the level
        lacks; under ``source``, the level's APB2 record. The level itself is left unchanged.
        """
        columns = _catalogued(self.name, self._sets)
        adata = self._stored.adata
        layers = {
            name: self._layer(entry.reference) for name, (_, entry) in columns["layers"].items()
        }
        var = pd.DataFrame(
            {
                name: self._var(entry.reference).set_axis(adata.var_names)
                for name, (_, entry) in columns["var"].items()
            },
            index=adata.var_names,
        )
        obs = pd.DataFrame(
            {
                name: self._obs(entry.reference).set_axis(adata.obs_names)
                for name, (_, entry) in columns["obs"].items()
            },
            index=adata.obs_names,
        )
        record: dict[str, object] = {
            "sets": list(self._sets.sets),
            **{slot: _described(found) for slot, found in columns.items()},
            "absent": _absent(self.name, self._sets, columns),
            "source": dict(self._stored.namespace),
        }
        return AnnData(obs=obs, var=var, layers=layers, uns={CATALOG: record})

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

    ``DataCatalog(mdata, "abundance_alpha", "confidence_alpha").levels["peptidoform_ion"].layers["pep"]`` is
    the PEP matrix AnnData holds; ``var["q_value"]`` a pandas Series. A MuData's levels are its
    modalities; an h5ad's one level is the AnnData itself.

    Raises:
        ValueError: The object holds no ``uns["apb"]``, so APB2 did not write it.
    """

    __slots__ = ("_namespace", "_sets", "levels")

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
        self._namespace = namespace
        self._sets = sets
        self.levels = {
            name: AnnDataLevel(name, level, lookup, sets) for name, level in stored.items()
        }

    def as_mudata(self) -> MuData:
        """Every level with a catalogued field as :meth:`AnnDataLevel.as_anndata` converts it, one
        modality each, under the level's name; ``uns["catalog"]`` names the sets and holds the
        object's APB2 record as ``source``. The object itself is left unchanged."""
        modalities = {name: level.as_anndata() for name, level in self.levels.items()}
        mdata = MuData(
            {
                name: adata
                for name, adata in modalities.items()
                if any(adata.uns[CATALOG][slot] for slot in _WRITTEN)
            }
        )
        mdata.uns[CATALOG] = {"sets": list(self._sets.sets), "source": dict(self._namespace)}
        return mdata


def _catalogued(
    level: str, sets: ComposedSets
) -> dict[Written, dict[str, tuple[str, SourceEntry]]]:
    """The fields the sets catalogue on one level, by slot, each under the name a conversion
    writes, with the set that catalogues it; a field one key names twice, once."""
    found: dict[tuple[str, Address], tuple[str, SourceEntry]] = {}
    for name, lookups in sets.sets.items():
        view = lookups.views.get(level)
        for entry in () if view is None else view.entries:
            found.setdefault((entry.key, entry.reference.address()), (name, entry))
    return {
        slot: _named([item for item in found.values() if _slot(item[1]) == slot])
        for slot in _WRITTEN
    }


def _slot(entry: SourceEntry) -> Written:
    location = entry.reference.location
    return "var" if location == "varm" else location


def _named(found: Sequence[tuple[str, SourceEntry]]) -> dict[str, tuple[str, SourceEntry]]:
    """Each field under its key; the fields one key names in one slot under the key and the
    qualifiers that tell them apart, ``key[name=value,…]``, and their own name where none does."""
    by_key: dict[str, list[tuple[str, SourceEntry]]] = {}
    for item in found:
        by_key.setdefault(item[1].key, []).append(item)
    named: dict[str, tuple[str, SourceEntry]] = {}
    for key, group in by_key.items():
        if len(group) == 1:
            named[key] = group[0]
            continue
        qualifiers = group[0][1].qualifiers
        differing = [
            name for name in qualifiers if len({entry.qualifiers[name] for _, entry in group}) > 1
        ]
        labels = [
            ",".join(f"{name}={entry.qualifiers[name]}" for name in differing) for _, entry in group
        ]
        for label, (set_name, entry) in zip(labels, group, strict=True):
            if label == "" or labels.count(label) > 1:
                label = ",".join(filter(None, (label, f"field={field_name(entry.reference)}")))
            named[f"{key}[{label}]"] = (set_name, entry)
    return named


def _described(found: Mapping[str, tuple[str, SourceEntry]]) -> dict[str, dict[str, object]]:
    """What each written column is: its set, key, qualifiers and the level's own name for it."""
    return {
        name: {
            "set": set_name,
            "key": entry.key,
            "qualifiers": dict(entry.qualifiers),
            "location": entry.reference.location,
            "name": field_name(entry.reference),
        }
        for name, (set_name, entry) in found.items()
    }


def _absent(
    level: str, sets: ComposedSets, columns: Mapping[Written, Mapping[str, tuple[str, SourceEntry]]]
) -> dict[str, dict[str, str]]:
    """The required and recommended keys no written field answers, by location."""
    written = [entry for found in columns.values() for _, entry in found.values()]
    absent: dict[str, dict[str, str]] = {}
    for lookups in sets.sets.values():
        for row in lookups.catalogues.requirements:
            if row.level != level or row.requirement == "optional":
                continue
            if not any(row.describes(entry) for entry in written):
                absent.setdefault(row.location, {})[row.key] = row.requirement
    return absent


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
