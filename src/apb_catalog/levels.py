"""A result's levels read through a catalog: AnnData's slots, looked up by key as cf_xarray does.

``DataCatalog(result, "abundance").levels["protein"].layers["maxlfq"]`` is the protein level's
MaxLFQ matrix, observations by variables. A name is looked up as one of the catalog's keys first,
then as the level's own name in that slot, and raises :class:`KeyError` when it is neither. As
AnnData, ``X`` and the layers are numpy matrices; ``var`` and ``obs`` columns are polars Series,
and a list of names, ``obs[["group"]]``, reads every column they name as a polars DataFrame.

``Catalog("DIA-NN", "1.9.2", "abundance").levels["peptidoform_ion"].layers["intensity"]`` is
``'Precursor_Quantity'``: the same slots without data hold names.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import overload, override

import numpy as np
import polars as pl
from apb2.api import ParsedLevel

from apb_catalog.rules import Location
from apb_catalog.source import Reference

type Matrix = np.ndarray[tuple[int, int], np.dtype[np.generic]]


@dataclass(frozen=True, slots=True)
class Lookup:
    """How a catalog answers keys on its levels."""

    field: Callable[[str, Location, str], Reference | None]
    """The one field a key names on a level and location, ``None`` when the level has none."""
    fields: Callable[[str, Location, str], tuple[Reference, ...]]
    """Every field a key names on a level and location."""
    offered: Callable[[str, Location], tuple[str, ...]]
    """The keys a level offers at a location."""
    known: frozenset[str]
    """Every key of the catalog."""


def field_name(reference: Reference) -> str:
    """A field's name in its slot; ``table/column`` for a column of a ``varm`` table."""
    name = reference.address()[2]
    return name if reference.table is None else f"{reference.table}/{name}"


class Level:
    """One level of a result, with AnnData's slots: ``X``, ``layers``, ``var``, ``obs``,
    ``obs_names`` and ``var_names``.

    ``X`` is the level's primary layer and ``layers`` its other layers, observations by
    variables; a key may name the primary layer, and then answers ``X``. A matrix is built once
    and shared by every later answer.
    """

    __slots__ = ("_level", "_matrices", "layers", "name", "obs", "var")

    def __init__(self, name: str, level: ParsedLevel, lookup: Lookup) -> None:
        self.name = name
        self._level = level
        self._matrices: dict[str, Matrix] = {}
        self.layers = Slot(name, "layers", lookup, self._layer, self._layer_names())
        self.var = Columns(name, "var", lookup, self._var, set(level.var.frame.columns), _frame)
        self.obs = Columns(name, "obs", lookup, self._obs, set(level.obs.frame.columns), _frame)

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


class LevelNames:
    """One level of a software version's rule, with the slots of :class:`Level` holding names:
    ``layers``, ``var`` and ``obs``.

    Without data there is no ``X``, ``obs_names`` or ``var_names``, and no own name to fall back
    on: a name that is no key the level answers raises :class:`KeyError`.
    """

    __slots__ = ("layers", "name", "obs", "var")

    def __init__(self, name: str, lookup: Lookup) -> None:
        self.name = name
        self.layers = Slot(name, "layers", lookup, field_name, set())
        self.var = Columns(name, "var", lookup, field_name, set(), _named)
        self.obs = Columns(name, "obs", lookup, field_name, set(), _named)


class Slot[Value]:
    """One slot of a level, read by key first and by the level's own name second.

    As cf_xarray's accessor: ``keys()`` and ``in`` know the catalog's keys only; the level's own
    names are read but not listed.
    """

    __slots__ = ("_level", "_location", "_lookup", "_named", "_read")

    def __init__(
        self,
        level: str,
        location: Location,
        lookup: Lookup,
        read: Callable[[Reference], Value],
        named: set[str],
    ) -> None:
        self._level = level
        self._location: Location = location
        self._lookup = lookup
        self._read = read
        self._named = named

    def __getitem__(self, name: str) -> Value:
        """The field a key names, else the level's own field of that name.

        Raises:
            KeyError: The name is neither a key the level answers nor one of its own names.
            UnresolvedField: The key names several fields, or one the catalogue cannot decide.
        """
        if name in self._lookup.known:
            found = self._lookup.field(self._level, self._location, name)
            if found is not None:
                return self._read(found)
        return self._read(self._own(name))

    def __contains__(self, name: object) -> bool:
        """Whether the level offers this key here."""
        return name in self.keys()

    def keys(self) -> set[str]:
        """The keys the level offers in this slot."""
        return set(self._lookup.offered(self._level, self._location))

    def _own(self, name: str) -> Reference:
        if name not in self._named:
            raise KeyError(f"{self._level} {self._location} has no key or field {name!r}")
        return Reference(level=self._level, location=self._location, name=name)


class Columns[Value, Frame](Slot[Value]):
    """A ``var`` or ``obs`` slot, also read by a list of names, as a polars DataFrame is.

    ``obs[["group"]]`` holds every column the key names, each under its own name, where
    ``obs["group"]`` raises because there are several.
    """

    __slots__ = ("_combine",)

    def __init__(
        self,
        level: str,
        location: Location,
        lookup: Lookup,
        read: Callable[[Reference], Value],
        named: set[str],
        combine: Callable[[Sequence[tuple[str, Value]]], Frame],
    ) -> None:
        super().__init__(level, location, lookup, read, named)
        self._combine = combine

    @overload
    def __getitem__(self, name: str) -> Value: ...
    @overload
    def __getitem__(self, name: list[str]) -> Frame: ...
    @override
    def __getitem__(self, name: str | list[str]) -> Value | Frame:
        """One field for a name; every field the names name, in order, for a list of names.

        Raises:
            KeyError: A name is neither a key the level answers nor one of its own names.
            UnresolvedField: A key may name a field the catalogue cannot decide.
        """
        if isinstance(name, str):
            return super().__getitem__(name)
        found = {
            reference.address(): reference for each in name for reference in self._fields(each)
        }
        return self._combine(
            [(field_name(reference), self._read(reference)) for reference in found.values()]
        )

    def _fields(self, name: str) -> tuple[Reference, ...]:
        if name in self._lookup.known:
            found = self._lookup.fields(self._level, self._location, name)
            if found:
                return found
        return (self._own(name),)


def _frame(columns: Sequence[tuple[str, pl.Series]]) -> pl.DataFrame:
    return pl.DataFrame([series.alias(name) for name, series in columns])


def _named(columns: Sequence[tuple[str, str]]) -> tuple[str, ...]:
    return tuple(name for name, _ in columns)


def _names(frame: pl.DataFrame, keys: tuple[str, ...], name: str) -> pl.Series:
    if not keys:
        return pl.Series(name, [str(index) for index in range(frame.height)], dtype=pl.String)
    joined = pl.concat_str([pl.col(key).cast(pl.String) for key in keys], separator="|")
    return frame.select(joined.alias(name)).to_series()
