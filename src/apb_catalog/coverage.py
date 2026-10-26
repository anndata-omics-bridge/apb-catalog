"""Which catalogued fields every packaged rule supplies, and whether each level meets its set.

A set with requirements judges each rule level: ``fail`` when a MUST field is unsupported,
``warn`` when a SHOULD or MAY field is, ``pass`` otherwise. A set without requirements reports
coverage only. Producer fields count where the rule's level retains their
column; fields a producer adds after conversion, such as apb-fasta's, count with what to run.
"""

from __future__ import annotations

from typing import Literal, cast

import polars as pl

from apb_catalog import rules
from apb_catalog.source import (
    Address,
    ProducerCatalogue,
    RequirementRow,
    RuleVariant,
    SourceCatalogues,
    SourceEntry,
    catalogue_descriptions,
    catalogue_set,
)

type Verdict = Literal["pass", "warn", "fail"]

VERSION_LABELS: dict[str, str] = {
    "^2\\.": "2.x",
    "^2\\..*": "2.x",
    "^1\\.": "1.x",
    "^1\\..*": "1.x",
    "^v?1\\..*": "1.x",
    "^0\\.": "0.x",
    "^0\\.5\\.": "0.5",
    "^.*$": "any",
    "^13(?:\\.|\\s|$)": "13",
    "^1\\.[0-7](\\.|$)": "1.0\u20131.7",
    "^1\\.[89](\\.|$)": "1.8\u20131.9",
    "^1\\.10(?:\\.|-|$)": "1.10",
    "^1\\.12(?:\\.|-|$)": "1.12",
    "^2[23]\\.": "22\u201323",
    "^(1\\.5|1\\.6|2\\.)": "1.5, 1.6, 2.x",
    "^(19|20)\\..*": "19\u201320",
    "^15\\..*": "15",
    "^21\\..*": "21",
    "^0\\.9\\.11$": "0.9.11",
}
"""Concise readings of the rules' version patterns; a new pattern needs a label here."""

COVERAGE_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "software": pl.String,
    "version": pl.String,
    "rule": pl.String,
    "level": pl.String,
    "kind": pl.String,
    "qualifiers": pl.String,
    "origin": pl.String,
    "producer": pl.String,
    "requirement": pl.String,
    "location": pl.String,
    "table": pl.String,
    "column": pl.String,
    "inputs": pl.List(pl.String),
    "needs": pl.String,
    "verdict": pl.String,
}
"""One row per catalogued or required field of one rule level; a level with neither has one
row without a kind."""

CATALOGUES_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "catalogue": pl.String,
    "purpose": pl.String,
    "used_by": pl.List(pl.String),
    "has_requirements": pl.Boolean,
    "entries": pl.UInt32,
}

_SEVERITY: dict[str, Verdict] = {"MUST": "fail", "SHOULD": "warn", "MAY": "warn"}


def version_label(pattern: str) -> str:
    """The concise reading of one rule's software version pattern."""
    if pattern not in VERSION_LABELS:
        raise KeyError(f"no version label for {pattern!r}; add one to VERSION_LABELS")
    return VERSION_LABELS[pattern]


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

    Columns: ``software``, ``version``, ``rule``, ``level``, ``kind``, ``qualifiers`` (the other
    qualifiers as ``key=value``), ``origin``, ``producer`` (null for the vendor's own fields),
    ``requirement``, ``location``, ``table``, ``column`` (null when unsupported), ``inputs``
    (the vendor columns APB2 computes the column from), ``needs`` (what to run before the field
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
                rule=found.rule,
                level=found.level,
                software_version_pattern=found.software_version_pattern,
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
    roles = rules.roles(variant.rule, variant.level)
    found += [
        (bound, producer)
        for producer in sources.producers
        for entry in producer.entries_on(variant.level)
        for bound in _bound(entry, roles)
        if _counts(producer, bound, variant)
    ]
    required = [row for row in sources.requirements if row.level == variant.level]
    missing = [row for row in required if not any(row.describes(entry) for entry, _ in found)]
    verdict = _verdict([row.requirement for row in missing]) if required else None
    base: dict[str, object] = {
        "software": software,
        "version": version_label(variant.software_version_pattern),
        "rule": variant.rule,
        "level": variant.level,
        "verdict": verdict,
    }
    rows = [
        {**base, **_field(entry, producer, variant), "requirement": _requirement(required, entry)}
        for entry, producer in found
    ]
    rows += [
        {
            **base,
            "kind": row.kind,
            "qualifiers": _pairs(row.qualifiers),
            "location": row.location,
            "requirement": row.requirement,
        }
        for row in missing
    ]
    if not rows:
        rows.append(base)
    return sorted(rows, key=lambda row: _position(required, row))


def _bound(entry: SourceEntry, roles: dict[str, str]) -> tuple[SourceEntry, ...]:
    """A producer entry bound to the rule's column: its role's column when it names a role."""
    role = entry.reference.role
    if role is None:
        return (entry,)
    return (entry.bound(roles[role]),) if role in roles else ()


def _requirement(required: list[RequirementRow], entry: SourceEntry) -> str | None:
    row = next((row for row in required if row.describes(entry)), None)
    return None if row is None else row.requirement


def _pairs(qualifiers: dict[str, str]) -> str | None:
    return ";".join(f"{name}={value}" for name, value in sorted(qualifiers.items())) or None


def _kind(entry: SourceEntry) -> str:
    return entry.qualifiers["kind"]


def _position(required: list[RequirementRow], row: dict[str, object]) -> tuple[int, bool]:
    kind = cast(str | None, row.get("kind"))
    rank = next(
        (index for index, found in enumerate(required) if found.kind == kind), len(required)
    )
    return (rank, row.get("producer") is not None)


def _verdict(requirements: list[str]) -> Verdict:
    severities = {_SEVERITY[requirement] for requirement in requirements}
    if "fail" in severities:
        return "fail"
    return "warn" if severities else "pass"


def _field(
    entry: SourceEntry, producer: ProducerCatalogue | None, variant: RuleVariant
) -> dict[str, object]:
    reference = entry.reference
    others = {name: value for name, value in entry.qualifiers.items() if name != "kind"}
    origin = others.pop("origin", None)
    inputs = (
        rules.var_inputs(variant.rule, variant.level, reference.address()[2])
        if reference.location == "var" and _retains(variant, reference.address())
        else ()
    )
    return {
        "kind": _kind(entry),
        "qualifiers": _pairs(others),
        "origin": origin,
        "producer": None if producer is None else producer.producer,
        "location": reference.location,
        "table": reference.table,
        "column": reference.name,
        "inputs": list(inputs),
        "needs": None if producer is None else producer.instruction,
    }


def _counts(producer: ProducerCatalogue, entry: SourceEntry, variant: RuleVariant) -> bool:
    """A producer field counts where conversion keeps its column, or once its producer runs."""
    return bool(producer.requires) or _retains(variant, entry.reference.address())


def _retains(variant: RuleVariant, address: Address) -> bool:
    return address in rules.retained(variant.rule, variant.level)
