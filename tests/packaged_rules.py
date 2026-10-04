"""The effective rules APB2 currently packages, for drift checks and result fixtures."""

from __future__ import annotations

import json
from functools import cache
from typing import cast

from apb2.api import JsonValue, packaged_rule_declarations

from apb_catalog.fingerprint import fingerprint


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


def current_fingerprints(rule: str, level: str) -> set[str]:
    """Return the fingerprints APB2 would store today for one packaged rule level."""
    return {fingerprint(payload) for payload in effective_rules()[(rule, level)]}


def declared_rule_json(rule: str, level: str) -> str:
    """Return a ``rule_json`` string exactly as conversion stores it for the first variant."""
    return _declarations()[(rule, level)][0]


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
