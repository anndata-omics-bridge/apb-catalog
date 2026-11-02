"""Every catalogue set as one long table: one row per entry and software version it applies to."""

from __future__ import annotations

import polars as pl

from apb_catalog.source import (
    SourceCatalogues,
    SourceEntry,
    catalogue_descriptions,
    catalogue_set,
)

KEY_COLUMNS = ("set", "source", "software_version_pattern", "level", "location", "table", "name")
"""The columns before the qualifiers; ``qualifier.<name>``, ``requirement`` and ``entry_id``
follow."""


def field_name(entry: SourceEntry, /) -> str:
    """The column an entry names: its name, or the prefix it is found by."""
    reference = entry.reference
    if reference.name is not None:
        return reference.name
    return f"prefix:{reference.prefix}"


def entry_row(
    set_name: str,
    sources: SourceCatalogues,
    source: str,
    software_version_pattern: str | None,
    entry: SourceEntry,
) -> dict[str, object]:
    """One table row: where the entry's field lives, its qualifiers and its requirement."""
    reference = entry.reference
    row = next((row for row in sources.requirements if row.describes(entry)), None)
    return {
        "set": set_name,
        "source": source,
        "software_version_pattern": software_version_pattern,
        "level": reference.level,
        "location": reference.location,
        "table": reference.table,
        "name": field_name(entry),
        **{f"qualifier.{name}": entry.qualifiers[name] for name in sources.vocabulary.qualifiers},
        "requirement": None if row is None else row.requirement,
        "entry_id": entry.entry_id,
    }


def set_rows(set_name: str, sources: SourceCatalogues) -> list[dict[str, object]]:
    """Every row of one set: vendor entries once per software version pattern, the others once,
    without a pattern."""
    rows: list[dict[str, object]] = []
    for vendor in sources.catalogues:
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


def schema(sources: SourceCatalogues, /) -> dict[str, type[pl.DataType]]:
    """The table's columns for one set: the key columns, its qualifiers, requirement, entry id."""
    columns = [*KEY_COLUMNS, *(f"qualifier.{name}" for name in sources.vocabulary.qualifiers)]
    return dict.fromkeys((*columns, "requirement", "entry_id"), pl.String)


def catalogue_table(catalogue: str | None = None) -> pl.DataFrame:
    """One set, or every packaged and plugin set, as one long table.

    Columns: ``set``, ``source`` (the conversion software, an app or
    ``annotation:<convention>``), ``software_version_pattern`` (null for an entry of every
    software version), ``level``, ``location``, ``table``, ``name`` (``prefix:<prefix>`` for a
    field found by column-name prefix), one ``qualifier.<name>`` column per qualifier,
    ``requirement`` and ``entry_id``. A row is identified by ``set``, ``entry_id`` and
    ``software_version_pattern``.

    Raises:
        ValueError: The catalogue set is neither packaged nor installed by a plugin.
    """
    names = list(catalogue_descriptions()) if catalogue is None else [catalogue]
    frames = [
        pl.DataFrame(set_rows(name, catalogue_set(name)), schema=schema(catalogue_set(name)))
        for name in names
    ]
    rows = pl.concat(frames, how="diagonal")
    qualifiers = [name for name in rows.columns if name.startswith("qualifier.")]
    return rows.select(*KEY_COLUMNS, *qualifiers, "requirement", "entry_id")
