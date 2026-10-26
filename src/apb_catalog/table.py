"""Every catalogue set as one long table: one row per entry and rule it applies to."""

from __future__ import annotations

import polars as pl

from apb_catalog.source import (
    SourceCatalogues,
    SourceEntry,
    catalogue_descriptions,
    catalogue_set,
)

KEY_COLUMNS = ("set", "source", "version_pattern", "rule", "level", "location", "table", "name")
"""The columns before the qualifiers; ``qualifier.<name>``, ``requirement`` and ``entry_id``
follow."""

ANY_RULE = "*"
"""The rule of an entry that applies to every rule: a producer's or a sample annotation's."""


def field_name(entry: SourceEntry, /) -> str:
    """The column an entry names: its name, or the role or prefix it is found by."""
    reference = entry.reference
    if reference.name is not None:
        return reference.name
    if reference.role is not None:
        return f"role:{reference.role}"
    return f"prefix:{reference.prefix}"


def entry_row(
    set_name: str,
    sources: SourceCatalogues,
    source: str,
    version_pattern: str | None,
    rule: str,
    entry: SourceEntry,
) -> dict[str, object]:
    """One table row: where the entry's field lives, its qualifiers and its requirement."""
    reference = entry.reference
    row = next((row for row in sources.requirements if row.describes(entry)), None)
    return {
        "set": set_name,
        "source": source,
        "version_pattern": version_pattern,
        "rule": rule,
        "level": reference.level,
        "location": reference.location,
        "table": reference.table,
        "name": field_name(entry),
        **{f"qualifier.{name}": entry.qualifiers[name] for name in sources.vocabulary.qualifiers},
        "requirement": None if row is None else row.requirement,
        "entry_id": entry.entry_id,
    }


def set_rows(set_name: str, sources: SourceCatalogues) -> list[dict[str, object]]:
    """Every row of one set: vendor entries once per rule, the others once."""
    rows: list[dict[str, object]] = []
    for vendor in sources.catalogues:
        patterns = {variant.rule: variant.software_version_pattern for variant in vendor.variants}
        for entry in vendor.entries:
            for rule in entry.rules:
                label = vendor.label
                rows.append(entry_row(set_name, sources, label, patterns[rule], rule, entry))
    for source in (*sources.producers, *sources.annotations):
        label = source.label
        rows += [
            entry_row(set_name, sources, label, None, ANY_RULE, entry) for entry in source.entries
        ]
    return rows


def schema(sources: SourceCatalogues, /) -> dict[str, type[pl.DataType]]:
    """The table's columns for one set: the key columns, its qualifiers, requirement, entry id."""
    columns = [*KEY_COLUMNS, *(f"qualifier.{name}" for name in sources.vocabulary.qualifiers)]
    return dict.fromkeys((*columns, "requirement", "entry_id"), pl.String)


def catalogue_table(catalogue: str | None = None) -> pl.DataFrame:
    """One set, or every packaged and plugin set, as one long table.

    Columns: ``set``, ``source`` (the vendor, ``producer:<name>`` or ``annotation:<convention>``),
    ``version_pattern``, ``rule`` (``*`` for an entry of every rule), ``level``, ``location``,
    ``table``, ``name`` (``role:<role>`` or ``prefix:<prefix>`` for a field found by role or
    column-name prefix), one ``qualifier.<name>`` column per qualifier, ``requirement`` and
    ``entry_id``. A row is identified by ``set``, ``entry_id`` and ``rule``.

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
