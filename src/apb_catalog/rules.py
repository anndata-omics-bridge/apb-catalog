"""The levels APB2 converts for each software version range, as the catalog's build wrote them.

Nothing here reads APB2's parse rules: ``scripts/rule_levels.py`` writes ``rule_levels.csv``
from them when the catalog is written.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

type Location = Literal["obs", "layers", "var", "varm"]
type Address = tuple[Location, str | None, str]

COLUMNS = ("software", "software_version_pattern", "version", "level")
"""The columns of ``rule_levels.csv``."""


@dataclass(frozen=True, slots=True)
class RuleLevel:
    """One level APB2 converts for a software version range, with the range's label."""

    software_name: str
    software_version_pattern: str
    version: str
    level: str


@cache
def rule_levels() -> tuple[RuleLevel, ...]:
    """Every packaged rule level, in APB2's order.

    Raises:
        ValueError: ``rule_levels.csv`` has other columns than ``COLUMNS``.
    """
    text = resources.files("apb_catalog").joinpath("data", "rule_levels.csv").read_text("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError(f"rule_levels.csv has the columns {reader.fieldnames}, not {COLUMNS}")
    return tuple(
        RuleLevel(row["software"], row["software_version_pattern"], row["version"], row["level"])
        for row in reader
    )


def matching(software: str, version: str) -> tuple[RuleLevel, ...]:
    """The packaged rule levels of one software whose version pattern admits a version."""
    return tuple(
        found
        for found in rule_levels()
        if found.software_name.lower() == software.lower()
        and re.search(found.software_version_pattern, version) is not None
    )


def version_label(pattern: str) -> str:
    """The concise reading of one rule's software version pattern.

    Raises:
        KeyError: No packaged rule declares the pattern.
    """
    for found in rule_levels():
        if found.software_version_pattern == pattern:
            return found.version
    raise KeyError(f"no packaged rule declares the version pattern {pattern!r}")
