"""What APB2's packaged rules declare: the fields each rule level keeps, its roles, its versions."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from typing import cast

from apb2.api import JsonValue, packaged_rule_declarations

from apb_catalog.source import Address, Location

type Declaration = dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class RuleLevel:
    """One packaged rule level and the software version range its rule declares."""

    rule: str
    level: str
    software_name: str
    software_version_pattern: str


@cache
def declarations(rule: str, level: str) -> tuple[Declaration, ...]:
    """Every effective declaration a packaged rule level can store; none for an unknown one."""
    texts = packaged_rule_declarations().get((rule, level), ())
    return tuple(cast(Declaration, json.loads(text)) for text in texts)


def declaration(rule: str, level: str) -> Declaration:
    """The first effective declaration of a packaged rule level."""
    found = declarations(rule, level)
    if not found:
        raise KeyError(f"no packaged rule {rule} declares the level {level}")
    return found[0]


@cache
def rule_levels() -> tuple[RuleLevel, ...]:
    """Every packaged rule level with its software name and version pattern."""
    found: list[RuleLevel] = []
    for rule, level in packaged_rule_declarations():
        stored = declaration(rule, level)
        found.append(
            RuleLevel(
                rule,
                level,
                cast(str, stored["software_name"]),
                cast(str, stored["software_version_pattern"]),
            )
        )
    return tuple(found)


def matching(software: str, version: str) -> tuple[RuleLevel, ...]:
    """The packaged rule levels of one software whose version pattern admits a version."""
    return tuple(
        found
        for found in rule_levels()
        if found.software_name.lower() == software.lower()
        and re.search(found.software_version_pattern, version) is not None
    )


def _columns(stored: Declaration, location: str) -> list[dict[str, JsonValue]]:
    columns = cast(dict[str, list[dict[str, JsonValue]]], stored.get("columns") or {})
    return columns.get(location, [])


def _layers(stored: Declaration) -> list[dict[str, JsonValue]]:
    measurements = cast(dict[str, list[dict[str, JsonValue]]], stored.get("measurements") or {})
    return measurements.get("layers", [])


def field(stored: Declaration, location: Location, name: str) -> dict[str, JsonValue] | None:
    """One field's declaration without its note, or ``None`` when the rule declares no such field.

    ``varm`` fields come from producers after conversion, so no rule declares them.
    """
    candidates = (
        _layers(stored)
        if location == "layers"
        else []
        if location == "varm"
        else _columns(stored, location)
    )
    for candidate in candidates:
        if candidate.get("name") == name:
            return {key: value for key, value in candidate.items() if key != "note"}
    return None


@cache
def retained(rule: str, level: str) -> frozenset[Address]:
    """The obs, var and layer fields a packaged rule level declares."""
    stored = declaration(rule, level)
    found: set[Address] = {("layers", None, cast(str, layer["name"])) for layer in _layers(stored)}
    for location in ("obs", "var"):
        found |= {
            (cast(Location, location), None, cast(str, column["name"]))
            for column in _columns(stored, location)
        }
    return frozenset(found)


@cache
def roles(rule: str, level: str) -> dict[str, str]:
    """The var column each role names on a packaged rule level."""
    found: dict[str, str] = {}
    for column in _columns(declaration(rule, level), "var"):
        for role in cast(list[str], column.get("roles") or []):
            found[role] = cast(str, column["name"])
    return found


def var_inputs(rule: str, level: str, name: str) -> tuple[str, ...]:
    """The vendor columns APB2 computes one var column of a packaged rule level from."""
    column = field(declaration(rule, level), "var", name)
    return () if column is None else tuple(cast(list[str], column.get("inputs") or []))
