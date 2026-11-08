"""The software versions APB2 converts, the levels the catalog's entries name for each, and the
entry ids that name them.

Nothing here reads APB2's parse rules: ``scripts/versions.py`` writes ``versions.csv`` from them
when the catalog is written, and a version's levels are the levels its packaged entries name.
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

COLUMNS = ("software", "version", "software_version_pattern")
"""The columns of ``versions.csv``."""

ANY = "*"
"""An entry id's version for every version of its source, later ones included; its level for
every level, which only an app's or an annotation convention's entries name."""
NONE = "-"
"""An entry id's key or column where its attribute has none."""
ATTRIBUTES: tuple[Location, ...] = ("obs", "var", "layers", "varm")


@dataclass(frozen=True, slots=True)
class EntryId:
    """An entry id's fields, built as CPE names are: ``<source>/<version>/<level>/<attribute>/
    <key>/<column>``, six fields of one value each.

    ``version`` is a label of ``versions.csv``, or ``*``. A layer's name is its key and a ``varm``
    column's table is its key; obs and var have none. ``name`` is the layer or column; a trailing
    ``*`` matches obs columns by prefix.
    """

    source: str
    version: str
    level: str
    attribute: Location
    table: str | None
    name: str


def entry_id(text: str, /) -> EntryId:
    """Parse one entry id.

    Raises:
        ValueError: The id has not six fields, names no AnnData attribute, leaves its source,
            version or level open, or writes ``-`` where the attribute has a key or column, or a
            name where it has none.
    """
    fields = text.split("/")
    if len(fields) != 6:
        raise ValueError(f"entry id {text!r} has {len(fields)} fields, not 6")
    source, version, level, attribute, key, column = fields
    if attribute not in ATTRIBUTES:
        raise ValueError(f"entry id {text!r}: {attribute!r} is none of {ATTRIBUTES}")
    found = attribute
    if NONE in (source, version, level) or source == ANY or "" in fields:
        raise ValueError(f"entry id {text!r} leaves its source, version or level open")
    has_key = found in ("layers", "varm")
    has_column = found != "layers"
    if (key != NONE) != has_key or (column != NONE) != has_column:
        raise ValueError(
            f"entry id {text!r}: {found} has {'a' if has_key else 'no'} key and "
            f"{'a' if has_column else 'no'} column"
        )
    if ANY in (key, column):
        raise ValueError(f"entry id {text!r} names no layer or column")
    return EntryId(
        source=source,
        version=version,
        level=level,
        attribute=found,
        table=key if found == "varm" else None,
        name=key if found == "layers" else column,
    )


@dataclass(frozen=True, slots=True)
class SoftwareVersion:
    """One software version range APB2 has a rule for: its label and the rule's version pattern."""

    software_name: str
    version: str
    software_version_pattern: str


@dataclass(frozen=True, slots=True)
class RuleLevel:
    """One level APB2 converts for a software version range, with the range's label."""

    software_name: str
    software_version_pattern: str
    version: str
    level: str


def _rows(table: str) -> list[dict[str, str]]:
    text = resources.files("apb_catalog").joinpath("data", f"{table}.csv").read_text("utf-8")
    return list(csv.DictReader(io.StringIO(text)))


@cache
def versions() -> tuple[SoftwareVersion, ...]:
    """Every software version APB2 has a rule for, in APB2's order.

    Raises:
        ValueError: ``versions.csv`` has other columns than ``COLUMNS``.
    """
    rows = _rows("versions")
    if rows and tuple(rows[0]) != COLUMNS:
        raise ValueError(f"versions.csv has the columns {tuple(rows[0])}, not {COLUMNS}")
    return tuple(
        SoftwareVersion(row["software"], row["version"], row["software_version_pattern"])
        for row in rows
    )


@cache
def rule_levels() -> tuple[RuleLevel, ...]:
    """Every level a packaged entry names for a software version: versions in ``versions.csv``'s
    order, each version's levels in the order the entries first name them; ``*`` names every
    version of its source."""
    named_ids = (f"{row['software']}/{row['location']}/{row['name']}" for row in _rows("catalog"))
    ids = [named for found in named_ids if (named := entry_id(found)).level != ANY]
    found: list[RuleLevel] = []
    for version in versions():
        for named in ids:
            if named.source != version.software_name or named.version not in (ANY, version.version):
                continue
            name, pattern = version.software_name, version.software_version_pattern
            level = RuleLevel(name, pattern, version.version, named.level)
            if level not in found:
                found.append(level)
    return tuple(found)


def matching(software: str, version: str) -> tuple[RuleLevel, ...]:
    """The packaged rule levels of one software whose version pattern admits a version."""
    return tuple(
        found
        for found in rule_levels()
        if found.software_name.lower() == software.lower()
        and re.search(found.software_version_pattern, version) is not None
    )


def version_pattern(software: str, version: str) -> str:
    """The rule's version pattern for one software's labelled version.

    Raises:
        KeyError: ``versions.csv`` has no such software version.
    """
    for found in versions():
        if found.software_name == software and found.version == version:
            return found.software_version_pattern
    raise KeyError(f"versions.csv has no {software} version {version!r}")


def version_patterns(software: str, version: str) -> tuple[str, ...]:
    """The rule version patterns an entry id's version names: one for a label, and for ``*``
    every pattern of the software, none for an app or an annotation convention.

    Raises:
        KeyError: ``versions.csv`` has no such software version.
    """
    if version != ANY:
        return (version_pattern(software, version),)
    return tuple(
        found.software_version_pattern for found in versions() if found.software_name == software
    )


def version_label(pattern: str) -> str:
    """The concise reading of one rule's software version pattern.

    Raises:
        KeyError: No packaged rule declares the pattern.
    """
    for found in versions():
        if found.software_version_pattern == pattern:
            return found.version
    raise KeyError(f"no packaged rule declares the version pattern {pattern!r}")
