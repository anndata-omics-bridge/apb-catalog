"""The effective rules APB2 currently packages, for drift checks and result fixtures.

These helpers read APB2's rule loader directly: catalogue review is bound to what APB2 ships,
and APB2 exposes no public listing of effective rules.
"""

from __future__ import annotations

import itertools
import json
from functools import cache
from typing import Literal, cast

from apb2.api import JsonValue
from apb2.parserV2.vendor_parse_rules.document import RuleNotApplicable, SearchParameterEvidence
from apb2.parserV2.vendor_parse_rules.loader import PACKAGED, load_rule_document

from apb_catalog.fingerprint import fingerprint

_ACQUISITION: tuple[Literal["DDA", "DIA", "unknown"], ...] = ("DDA", "DIA", "unknown")
_COMBINE: tuple[bool | None, ...] = (True, False, None)


def _relative(path: object) -> str:
    return str(path).split("documents/", 1)[1]


@cache
def effective_rules() -> dict[tuple[str, str], tuple[dict[str, JsonValue], ...]]:
    """Map each packaged (rule, level) to every distinct effective rule the evidence selects."""
    rules: dict[tuple[str, str], tuple[dict[str, JsonValue], ...]] = {}
    for path in PACKAGED:
        document = load_rule_document(path)
        for level in document.levels:
            variants: dict[str, dict[str, JsonValue]] = {}
            for acquisition, combine in itertools.product(_ACQUISITION, _COMBINE):
                evidence = SearchParameterEvidence(
                    acquisition_method=acquisition, combine_charge_states=combine
                )
                try:
                    effective = document.rule(level, evidence)
                except RuleNotApplicable:
                    continue
                payload = cast(dict[str, JsonValue], effective.declaration.model_dump(mode="json"))
                variants[fingerprint(payload)] = payload
            rules[(_relative(path), level)] = tuple(variants.values())
    return rules


def current_fingerprints(rule: str, level: str) -> set[str]:
    """Return the fingerprints APB2 would store today for one packaged rule level."""
    return {fingerprint(payload) for payload in effective_rules()[(rule, level)]}


def declared_rule_json(rule: str, level: str) -> str:
    """Return a ``rule_json`` string exactly as conversion stores it for the first variant."""
    return json.dumps(effective_rules()[(rule, level)][0])


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
