"""Which cataloged fields every packaged rule supplies, and whether each level meets its set.

A set with requirements judges each rule level: ``fail`` when a required field is unsupported,
``warn`` when a recommended one is, ``pass`` otherwise; an unsupported optional field is listed
but passes. A set without requirements reports coverage only. Fields an app such as apb-fasta adds after conversion count on every level, with
what to run.
"""

from __future__ import annotations

from typing import Literal, cast

import polars as pl

from apb_catalog import rules
from apb_catalog.source import (
    LoadedSet,
    ProducerEntries,
    RequirementRow,
    RuleVariant,
    SourceEntry,
    load_set,
    set_descriptions,
)
from apb_catalog.table import qualifier_names

type Verdict = Literal["pass", "warn", "fail"]

COVERAGE_COLUMNS = (
    "software",
    "version",
    "software_version_pattern",
    "level",
    "slot",
    "table",
    "name",
    "key",
    "kind",
)
"""The columns before the set's ``qualifier.<name>`` columns; ``producer``, ``requirement``,
``needs`` and ``verdict`` follow. One row per cataloged or required field of one rule level; a
level with neither has one row without a key."""

SETS_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "set": pl.String,
    "prefix": pl.String,
    "purpose": pl.String,
    "used_by": pl.List(pl.String),
    "has_requirements": pl.Boolean,
    "entries": pl.UInt32,
}

_SEVERITY: dict[str, Verdict] = {"required": "fail", "recommended": "warn", "optional": "pass"}


def sets() -> pl.DataFrame:
    """List every packaged and plugin set: the prefix that asks it alone, purpose,
    users, and entry count."""
    rows: list[dict[str, object]] = []
    for name, description in set_descriptions().items():
        sources = load_set(name)
        rows.append(
            {
                "set": name,
                "prefix": sources.vocabulary.prefix,
                "purpose": description.purpose,
                "used_by": list(description.used_by),
                "has_requirements": bool(sources.requirements),
                "entries": sum(len(source.entries) for source in sources.sources()),
            }
        )
    return pl.DataFrame(rows, schema=SETS_SCHEMA)


def rule_coverage(set_name: str) -> pl.DataFrame:
    """Check every packaged rule level against one set, one row per field.

    Columns: ``software`` (the quantification software of the rule), ``version`` (the label),
    ``software_version_pattern``, ``level``, ``slot``, ``table`` (the ``varm`` table, else
    null), ``name`` (the field's name, null when unsupported), ``key``, ``kind``, one
    ``qualifier.<name>`` column per other qualifier of the set, as in
    :func:`~apb_catalog.table.catalog_table`, ``producer`` (the app, null for the quantification
    software's fields), ``requirement``, ``needs`` (what to run before the field exists) and
    ``verdict`` (the rule level's, null for a set without requirements).

    Raises:
        ValueError: The set is neither packaged nor installed by a plugin.
    """
    return coverage_of(load_set(set_name))


def coverage_of(sources: LoadedSet) -> pl.DataFrame:
    """Check every rule variant of one loaded set; see :func:`rule_coverage`.

    A set without vendor entries answers for every packaged rule level, so each is checked.
    """
    rows: list[dict[str, object]] = []
    for vendor in sources.vendors:
        for variant in vendor.variants:
            rows += _variant_rows(
                sources, vendor.software_name, variant, vendor.entries_for(variant)
            )
    if not sources.needs_review:
        for found in rules.rule_levels():
            variant = RuleVariant(
                level=found.level, software_version_pattern=found.software_version_pattern
            )
            rows += _variant_rows(sources, found.software_name, variant, ())
    return pl.DataFrame(rows, schema=coverage_schema(sources))


def coverage_schema(sources: LoadedSet) -> dict[str, type[pl.DataType]]:
    """The coverage table's columns for one set: see :func:`rule_coverage`."""
    columns = (
        *COVERAGE_COLUMNS,
        *(f"qualifier.{name}" for name in qualifier_names(sources)),
        "producer",
        "requirement",
        "needs",
        "verdict",
    )
    return dict.fromkeys(columns, pl.String)


def _variant_rows(
    sources: LoadedSet,
    software: str,
    variant: RuleVariant,
    vendor_entries: tuple[SourceEntry, ...],
) -> list[dict[str, object]]:
    found: list[tuple[SourceEntry, ProducerEntries | None]] = [
        (entry, None) for entry in vendor_entries
    ]
    found += [
        (entry, producer)
        for producer in sources.producers
        for entry in producer.entries_on(variant.level)
    ]
    required = [row for row in sources.requirements if row.level == variant.level]
    missing = [row for row in required if not any(row.describes(entry) for entry, _ in found)]
    verdict = _verdict([row.requirement for row in missing]) if required else None
    base: dict[str, object] = {
        "software": software,
        "version": rules.version_label(variant.software_version_pattern),
        "software_version_pattern": variant.software_version_pattern,
        "level": variant.level,
        "verdict": verdict,
    }
    rows = [
        {
            **base,
            **_field(sources, entry, producer),
            "requirement": _requirement(required, entry),
        }
        for entry, producer in found
    ]
    rows += [
        {
            **base,
            **_meaning(sources, row.key),
            "slot": row.location,
            "requirement": row.requirement,
        }
        for row in missing
    ]
    if not rows:
        rows.append(base)
    return sorted(rows, key=lambda row: _position(required, row))


def _requirement(required: list[RequirementRow], entry: SourceEntry) -> str | None:
    row = next((row for row in required if row.describes(entry)), None)
    return None if row is None else row.requirement


def _qualifiers(sources: LoadedSet, values: dict[str, str]) -> dict[str, object]:
    """One ``qualifier.<name>`` column per qualifier of the set, null where no value is given."""
    return {f"qualifier.{name}": values.get(name) for name in qualifier_names(sources)}


def _meaning(sources: LoadedSet, key: str) -> dict[str, object]:
    """The key, kind and fixed qualifiers of a required key no entry supplies."""
    found = sources.key(key)
    return {"key": key, "kind": found.kind, **_qualifiers(sources, found.fixed)}


def _position(required: list[RequirementRow], row: dict[str, object]) -> tuple[int, bool]:
    key = cast(str | None, row.get("key"))
    rank = next((index for index, found in enumerate(required) if found.key == key), len(required))
    return (rank, row.get("producer") is not None)


def _verdict(requirements: list[str]) -> Verdict:
    severities = {_SEVERITY[requirement] for requirement in requirements}
    if "fail" in severities:
        return "fail"
    return "warn" if "warn" in severities else "pass"


def _field(
    sources: LoadedSet, entry: SourceEntry, producer: ProducerEntries | None
) -> dict[str, object]:
    reference = entry.reference
    return {
        "slot": reference.location,
        "table": reference.table,
        "name": reference.name,
        "key": entry.key,
        "kind": entry.kind,
        **_qualifiers(sources, entry.qualifiers),
        "producer": None if producer is None else producer.producer,
        "needs": None if producer is None else producer.instruction,
    }
