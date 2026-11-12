"""Every set as one long table: one row per entry and software version it applies to."""

from __future__ import annotations

import polars as pl

from apb_catalog.rules import ANY, version_label
from apb_catalog.source import (
    LoadedSet,
    SourceEntry,
    load_set,
    set_descriptions,
)

KEY_COLUMNS = (
    "set",
    "source",
    "version",
    "software_version_pattern",
    "level",
    "slot",
    "table",
    "name",
)
"""The columns before the meaning; ``key``, ``kind``, ``qualifier.<name>`` for each other
qualifier, ``requirement`` and ``entry_id`` follow."""


def qualifier_names(sources: LoadedSet, /) -> tuple[str, ...]:
    """The set's qualifiers, in vocabulary order; the kind is a column of its own."""
    return tuple(sources.vocabulary.qualifiers)


def entry_version(entry: SourceEntry, software_version_pattern: str | None) -> str:
    """The entry's version label: the one its id names, and for a vendor entry of every version
    (``*``) the label of the pattern the row applies to; apps and annotations keep ``*``."""
    named = entry.entry_id.split("/")[1]
    if named == ANY and entry.software_version_pattern and software_version_pattern is not None:
        return version_label(software_version_pattern)
    return named


def field_name(entry: SourceEntry, /) -> str:
    """The column an entry names: its name, or the prefix it is found by."""
    reference = entry.reference
    if reference.name is not None:
        return reference.name
    return f"prefix:{reference.prefix}"


def entry_row(
    set_name: str,
    sources: LoadedSet,
    source: str,
    software_version_pattern: str | None,
    entry: SourceEntry,
) -> dict[str, object]:
    """One table row: who writes the field and for which version, where it lives, its key and
    qualifiers, its requirement."""
    reference = entry.reference
    row = next((row for row in sources.requirements if row.describes(entry)), None)
    return {
        "set": set_name,
        "source": source,
        "version": entry_version(entry, software_version_pattern),
        "software_version_pattern": software_version_pattern,
        "level": reference.level,
        "slot": reference.location,
        "table": reference.table,
        "name": field_name(entry),
        "key": entry.key,
        "kind": entry.kind,
        **{f"qualifier.{name}": entry.qualifiers[name] for name in qualifier_names(sources)},
        "requirement": None if row is None else row.requirement,
        "entry_id": entry.entry_id,
    }


def set_rows(set_name: str, sources: LoadedSet) -> list[dict[str, object]]:
    """Every row of one set: vendor entries once per software version pattern, the others once,
    without a pattern."""
    rows: list[dict[str, object]] = []
    for vendor in sources.vendors:
        for entry in vendor.entries:
            rows += [
                entry_row(set_name, sources, vendor.label, pattern, entry)
                for pattern in entry.software_version_pattern
            ]
    for source in (*sources.producers, *sources.annotations):
        rows += [
            entry_row(set_name, sources, source.label, None, entry) for entry in source.entries
        ]
    return rows


def schema(sources: LoadedSet, /) -> dict[str, type[pl.DataType]]:
    """The table's columns for one set: the key columns, key, kind, its other qualifiers,
    requirement, entry id."""
    columns = [
        *KEY_COLUMNS,
        "key",
        "kind",
        *(f"qualifier.{name}" for name in qualifier_names(sources)),
    ]
    return dict.fromkeys((*columns, "requirement", "entry_id"), pl.String)


def catalog_table(set_name: str | None = None) -> pl.DataFrame:
    """The whole catalog, every packaged and plugin set, or one set, as one long table.

    Columns: ``set``, ``source`` (who writes the field: the quantification software, an app or
    ``annotation:<convention>``), ``version`` (the version label; ``*`` for an app's or an
    annotation's entry, which applies to every version), ``software_version_pattern`` (null for
    an entry of every software version), ``level``, ``slot`` (``layers``, ``var``, ``obs`` or
    ``varm``), ``table`` (the ``varm`` table, else null), ``name`` (the field's name;
    ``prefix:<prefix>`` for a field found by column-name prefix), ``key``, ``kind``, one
    ``qualifier.<name>`` column per other qualifier, ``requirement`` and ``entry_id``. A row is
    identified by ``set``, ``entry_id``, ``kind`` and ``software_version_pattern``.

    Raises:
        ValueError: The set is neither packaged nor installed by a plugin.
    """
    names = list(set_descriptions()) if set_name is None else [set_name]
    frames = [
        pl.DataFrame(set_rows(name, load_set(name)), schema=schema(load_set(name)))
        for name in names
    ]
    rows = pl.concat(frames, how="diagonal")
    qualifiers = [name for name in rows.columns if name.startswith("qualifier.")]
    return rows.select(*KEY_COLUMNS, "key", "kind", *qualifiers, "requirement", "entry_id")
