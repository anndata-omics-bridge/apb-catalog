"""Which catalogued fields every packaged rule supplies, and whether each level meets its set.

A set with requirements judges each rule level: ``fail`` when a MUST field is unsupported,
``warn`` when a SHOULD or MAY field is, ``pass`` otherwise. A set without requirements reports
coverage only. Producer fields count where the rule's level retains their
column; fields a producer adds after conversion, such as apb-fasta's, count with what to run.
"""

from __future__ import annotations

import json
from functools import cache
from typing import Literal, cast

import polars as pl
from apb2.api import JsonValue, packaged_rule_declarations

from apb_catalog.source import (
    Address,
    ProducerCatalogue,
    RuleVariant,
    SourceCatalogue,
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
                "entries": sum(
                    len(source.entries) for source in (*sources.catalogues, *sources.producers)
                ),
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
    """Check every rule variant of one loaded catalogue set; see :func:`rule_coverage`."""
    rows: list[dict[str, object]] = []
    for vendor in sources.catalogues:
        for variant in vendor.variants:
            rows += _variant_rows(sources, vendor, variant)
    return pl.DataFrame(rows, schema=COVERAGE_SCHEMA)


def _variant_rows(
    sources: SourceCatalogues, vendor: SourceCatalogue, variant: RuleVariant
) -> list[dict[str, object]]:
    found = [(entry, None) for entry in vendor.entries_for(variant)]
    found += [
        (entry, producer)
        for producer in sources.producers
        for entry in producer.entries_on(variant.level)
        if _counts(producer, entry, variant)
    ]
    required = sources.requirements.get(variant.level, {})
    missing = [kind for kind in required if not any(e.qualifiers["kind"] == kind for e, _ in found)]
    verdict = _verdict([required[kind] for kind in missing]) if required else None
    base: dict[str, object] = {
        "software": vendor.software_name,
        "version": version_label(variant.software_version_pattern),
        "rule": variant.rule,
        "level": variant.level,
        "verdict": verdict,
    }
    rows = [
        {**base, **_field(entry, producer, variant), "requirement": required.get(_kind(entry))}
        for entry, producer in found
    ]
    rows += [{**base, "kind": kind, "requirement": required[kind]} for kind in missing]
    if not rows:
        rows.append(base)
    order = list(required)
    return sorted(rows, key=lambda row: _position(order, row))


def _kind(entry: SourceEntry) -> str:
    return entry.qualifiers["kind"]


def _position(order: list[str], row: dict[str, object]) -> tuple[int, bool]:
    kind = cast(str | None, row.get("kind"))
    rank = order.index(kind) if kind is not None and kind in order else len(order)
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
        _var_inputs(variant.rule, variant.level, reference.name)
        if reference.location == "var" and _retains(variant, reference.address())
        else ()
    )
    return {
        "kind": _kind(entry),
        "qualifiers": ";".join(f"{name}={value}" for name, value in sorted(others.items())) or None,
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
    return address in _retained(variant.rule, variant.level)


@cache
def _declaration(rule: str, level: str) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], json.loads(packaged_rule_declarations()[(rule, level)][0]))


@cache
def _retained(rule: str, level: str) -> frozenset[Address]:
    declaration = _declaration(rule, level)
    measurements = cast(dict[str, list[dict[str, str]]], declaration["measurements"])
    columns = cast(dict[str, list[dict[str, str]]], declaration["columns"])
    layers = {("layers", None, layer["name"]) for layer in measurements["layers"]}
    var = {("var", None, column["name"]) for column in columns.get("var", [])}
    return frozenset(cast(set[Address], layers | var))


def _var_inputs(rule: str, level: str, name: str) -> tuple[str, ...]:
    columns = cast(dict[str, list[dict[str, JsonValue]]], _declaration(rule, level)["columns"])
    column = next(column for column in columns.get("var", []) if column["name"] == name)
    return tuple(cast(list[str], column.get("inputs") or []))
