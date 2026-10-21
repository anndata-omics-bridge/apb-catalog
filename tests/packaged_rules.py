"""The effective rules APB2 currently packages, for consistency checks and result fixtures."""

from __future__ import annotations

import json
from functools import cache
from typing import cast

from apb2.api import JsonValue, packaged_rule_declarations


@cache
def _declarations() -> dict[tuple[str, str], tuple[str, ...]]:
    return packaged_rule_declarations()


@cache
def effective_rules() -> dict[tuple[str, str], tuple[dict[str, JsonValue], ...]]:
    """Map each packaged (rule, level) to every distinct effective rule the evidence selects."""
    return {
        key: tuple(cast(dict[str, JsonValue], json.loads(text)) for text in texts)
        for key, texts in _declarations().items()
    }


def declared_software_versions(rule: str, level: str) -> set[tuple[str, str]]:
    """Return the software name and version pattern one packaged rule level declares."""
    return {
        (str(payload["software_name"]), str(payload["software_version_pattern"]))
        for payload in effective_rules()[(rule, level)]
    }


def declared_rule_json(rule: str, level: str) -> str:
    """Return a ``rule_json`` string exactly as conversion stores it for the first variant."""
    return _declarations()[(rule, level)][0]


def declared_var_column(rule: str, level: str, name: str) -> dict[str, JsonValue]:
    """Return one var column's declaration, as the first effective rule of a level states it."""
    columns = cast(
        dict[str, list[dict[str, JsonValue]]], effective_rules()[(rule, level)][0]["columns"]
    )
    return next(column for column in columns.get("var", []) if column["name"] == name)


def abundance_layers(rule: str, level: str) -> set[str]:
    """Return the layers a packaged rule level marks with the role ``abundance``."""
    payload = effective_rules()[(rule, level)][0]
    measurements = cast(dict[str, list[dict[str, JsonValue]]], payload["measurements"])
    return {
        str(layer["name"])
        for layer in measurements["layers"]
        if "abundance" in cast(list[str], layer.get("roles", []))
    }


def retained_sources(rule: str, level: str) -> dict[tuple[str, str], str]:
    """Map every (location, APB name) a packaged rule level retains to its vendor source."""
    payload = effective_rules()[(rule, level)][0]
    measurements = cast(dict[str, list[dict[str, str]]], payload["measurements"])
    columns = cast(dict[str, list[dict[str, str]]], payload["columns"])
    sources = {
        ("layers", layer["name"]): layer.get("source", "") for layer in measurements["layers"]
    }
    sources |= {
        ("var", column["name"]): column.get("source", "") for column in columns.get("var", [])
    }
    return sources
