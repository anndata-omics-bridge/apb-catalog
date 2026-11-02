"""A result's levels read through a catalog: AnnData's slots, looked up by key as cf_xarray does.

``DataCatalog(result, "abundance").levels["protein"].layers["maxlfq"]`` is the protein level's
MaxLFQ matrix, observations by variables. A name is looked up as one of the catalog's keys first,
then as the level's own name in that slot, and raises :class:`KeyError` when it is neither. As
AnnData, ``X`` and the layers are numpy matrices; ``var`` and ``obs`` columns are polars Series.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import polars as pl
from apb2.api import ParsedLevel

from apb_catalog.rules import Location
from apb_catalog.source import Reference

type Find = Callable[[str, Location, str], Reference | None]
"""The field a key names on a level and location, ``None`` when the level has none."""
type Offered = Callable[[str, Location], tuple[str, ...]]
"""The keys a level offers at a location."""
type Matrix = np.ndarray[tuple[int, int], np.dtype[np.generic]]


class Level:
    """One level of a result, with AnnData's slots: ``X``, ``layers``, ``var``, ``obs``,
    ``obs_names`` and ``var_names``.

    ``X`` is the level's primary layer and ``layers`` its other layers, observations by
    variables; a key may name the primary layer, and then answers ``X``. A matrix is built once
    and shared by every later answer.
    """

    __slots__ = ("_level", "_matrices", "layers", "name", "obs", "var")

    def __init__(
        self, name: str, level: ParsedLevel, find: Find, offered: Offered, known: frozenset[str]
    ) -> None:
        self.name = name
        self._level = level
        self._matrices: dict[str, Matrix] = {}
        self.layers = Slot(name, "layers", find, offered, known, self._layer, self._layer_names())
        self.var = Slot(name, "var", find, offered, known, self._var, set(level.var.frame.columns))
        self.obs = Slot(name, "obs", find, offered, known, self._obs, set(level.obs.frame.columns))

    @property
    def X(self) -> Matrix:
        """The primary layer, observations by variables."""
        return self._matrix(self._level.primary_layer_name)

    @property
    def obs_names(self) -> pl.Series:
        """One name per observation: its key columns, joined by ``|``."""
        return _names(self._level.obs.frame, self._level.obs.key_columns, "obs_names")

    @property
    def var_names(self) -> pl.Series:
        """One name per variable: its key columns, joined by ``|``."""
        return _names(self._level.var.frame, self._level.var.key_columns, "var_names")

    def _layer_names(self) -> set[str]:
        return set(self._level.layers) - {self._level.primary_layer_name}

    def _matrix(self, name: str) -> Matrix:
        if name not in self._matrices:
            self._matrices[name] = self._level.layers[name].wide().to_numpy().T
        return self._matrices[name]

    def _layer(self, reference: Reference) -> Matrix:
        return self._matrix(reference.address()[2])

    def _var(self, reference: Reference) -> pl.Series:
        name = reference.address()[2]
        if reference.table is None:
            return self._level.var.frame[name]
        return self._level.varm[reference.table][name]

    def _obs(self, reference: Reference) -> pl.Series:
        return self._level.obs.frame[reference.address()[2]]


class Slot[Value]:
    """One slot of a level, read by key first and by the level's own name second.

    As cf_xarray's accessor: ``keys()`` and ``in`` know the catalog's keys only; the level's own
    names are read but not listed.
    """

    __slots__ = ("_find", "_known", "_level", "_location", "_named", "_offered", "_read")

    def __init__(
        self,
        level: str,
        location: Location,
        find: Find,
        offered: Offered,
        known: frozenset[str],
        read: Callable[[Reference], Value],
        named: set[str],
    ) -> None:
        self._level = level
        self._location: Location = location
        self._find = find
        self._offered = offered
        self._known = known
        self._read = read
        self._named = named

    def __getitem__(self, name: str) -> Value:
        """The field a key names, else the level's own field of that name.

        Raises:
            KeyError: The name is neither a key the level answers nor one of its own names.
            UnresolvedField: The key names several fields, or one the catalogue cannot decide.
        """
        if name in self._known:
            found = self._find(self._level, self._location, name)
            if found is not None:
                return self._read(found)
        if name in self._named:
            return self._read(Reference(level=self._level, location=self._location, name=name))
        raise KeyError(f"{self._level} {self._location} has no key or field {name!r}")

    def __contains__(self, name: object) -> bool:
        """Whether the level offers this key here."""
        return name in self.keys()

    def keys(self) -> set[str]:
        """The keys the level offers in this slot."""
        return set(self._offered(self._level, self._location))


def _names(frame: pl.DataFrame, keys: tuple[str, ...], name: str) -> pl.Series:
    if not keys:
        return pl.Series(name, [str(index) for index in range(frame.height)], dtype=pl.String)
    joined = pl.concat_str([pl.col(key).cast(pl.String) for key in keys], separator="|")
    return frame.select(joined.alias(name)).to_series()
