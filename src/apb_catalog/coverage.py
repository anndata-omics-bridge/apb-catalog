"""Which catalogued fields every packaged rule supplies, and whether each level meets its set.

A set with requirements judges each rule level: ``fail`` when a MUST field is unsupported,
``warn`` when a SHOULD or MAY field is, ``pass`` otherwise. A set without requirements reports
coverage only. Fields an app such as apb-fasta adds after conversion count on every level, with
what to run.
"""

from __future__ import annotations

from typing import Literal, cast

import polars as pl

from apb_catalog import rules
from apb_catalog.source import (
    ProducerCatalogue,
    RequirementRow,
    RuleVariant,
    SourceCatalogues,
    SourceEntry,
    catalogue_descriptions,
    catalogue_set,
)

type Verdict = Literal["pass", "warn", "fail"]

COVERAGE_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "software": pl.String,
    "version": pl.String,
    "software_version_pattern": pl.String,
    "level": pl.String,
    "key": pl.String,
    "kind": pl.String,
    "qualifiers": pl.String,
    "origin": pl.String,
    "producer": pl.String,
    "requirement": pl.String,
    "location": pl.String,
    "table": pl.String,
    "column": pl.String,
    "needs": pl.String,
    "verdict": pl.String,
}
"""One row per catalogued or required field of one rule level; a level with neither has one
row without a key."""

CATALOGUES_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "catalogue": pl.String,
    "purpose": pl.String,
    "used_by": pl.List(pl.String),
    "has_requirements": pl.Boolean,
    "entries": pl.UInt32,
}

_SEVERITY: dict[str, Verdict] = {"MUST": "fail", "SHOULD": "warn", "MAY": "warn"}


def catalogues() -> pl.DataFrame:
    """List every packaged and plugin catalogue set: purpose, users, and entry count."""
    rows: list[dict[str, object]] = []
    for name, description in catalogue_descriptions().items():
        sources = catalogue_set(name)
        rows.append(
            {
                "catalogue": name,
                "purpose": description.purpose,
                "used_by": list(description.used_by),
                "has_requirements": bool(sources.requirements),
                "entries": sum(len(source.entries) for source in sources.sources()),
            }
        )
    return pl.DataFrame(rows, schema=CATALOGUES_SCHEMA)


def rule_coverage(catalogue: str) -> pl.DataFrame:
    """Check every packaged rule level against one catalogue set, one row per field.

    Columns: ``software``, ``version`` (the label), ``software_version_pattern``, ``level``,
    ``key``, ``kind``, ``qualifiers`` (the other qualifiers as ``name=value``), ``origin``,
    ``producer``
    (the app, null for the conversion software's fields), ``requirement``, ``location``,
    ``table``, ``column`` (null when unsupported), ``needs`` (what to run before the field
    exists) and ``verdict`` (the rule level's, null for a set without requirements).

    Raises:
        ValueError: The catalogue set is neither packaged nor installed by a plugin.
    """
    return coverage_of(catalogue_set(catalogue))


def coverage_of(sources: SourceCatalogues) -> pl.DataFrame:
    """Check every rule variant of one loaded catalogue set; see :func:`rule_coverage`.

    A set without vendor catalogues answers for every packaged rule level, so each is checked.
    """
    rows: list[dict[str, object]] = []
    for vendor in sources.catalogues:
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
    return pl.DataFrame(rows, schema=COVERAGE_SCHEMA)


def _variant_rows(
    sources: SourceCatalogues,
    software: str,
    variant: RuleVariant,
    vendor_entries: tuple[SourceEntry, ...],
) -> list[dict[str, object]]:
    found: list[tuple[SourceEntry, ProducerCatalogue | None]] = [
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
        {**base, **_field(entry, producer), "requirement": _requirement(required, entry)}
        for entry, producer in found
    ]
    rows += [
        {
            **base,
            **_meaning(sources, row.key),
            "location": row.location,
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


def _pairs(qualifiers: dict[str, str]) -> str | None:
    return ";".join(f"{name}={value}" for name, value in sorted(qualifiers.items())) or None


def _meaning(sources: SourceCatalogues, key: str) -> dict[str, object]:
    """The key, kind and other qualifiers of a required key no entry supplies."""
    found = sources.key(key)
    return {"key": key, "kind": found.kind, "qualifiers": _pairs(found.fixed)}


def _position(required: list[RequirementRow], row: dict[str, object]) -> tuple[int, bool]:
    key = cast(str | None, row.get("key"))
    rank = next((index for index, found in enumerate(required) if found.key == key), len(required))
    return (rank, row.get("producer") is not None)


def _verdict(requirements: list[str]) -> Verdict:
    severities = {_SEVERITY[requirement] for requirement in requirements}
    if "fail" in severities:
        return "fail"
    return "warn" if severities else "pass"


def _field(entry: SourceEntry, producer: ProducerCatalogue | None) -> dict[str, object]:
    reference = entry.reference
    others = {name: value for name, value in entry.qualifiers.items() if name != "kind"}
    origin = others.pop("origin", None)
    return {
        "key": entry.key,
        "kind": entry.qualifiers["kind"],
        "qualifiers": _pairs(others),
        "origin": origin,
        "producer": None if producer is None else producer.producer,
        "location": reference.location,
        "table": reference.table,
        "column": reference.name,
        "needs": None if producer is None else producer.instruction,
    }
