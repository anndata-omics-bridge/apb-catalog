"""Command line: list the catalogues and check the packaged APB2 rules against one."""

from __future__ import annotations

import sys
from typing import cast

import polars as pl
from cyclopts import App

from apb_catalog.api import catalogues, rule_coverage

app = App(
    name="apb-catalog",
    help="List APB catalogues and check the packaged APB2 rules against one",
    help_on_error=True,
)

_LABELS = {"fail": "FAIL", "warn": "WARN", "pass": "PASS"}


@app.default
def overview() -> int:
    """List every catalogue set, its entries, and whether it sets requirements."""
    for row in catalogues().iter_rows(named=True):
        checked = "requirements" if row["has_requirements"] else "coverage only"
        print(f"{row['catalogue']}: {row['entries']} entries, {checked}")
        print(f"    {row['purpose']}")
    return 0


@app.command
def check(catalogue: str, software: str | None = None, /) -> int:
    """Check every packaged rule level against CATALOGUE; exit 1 when one misses a MUST field.

    Each line is FAIL, WARN or PASS with the rule level and its unsupported fields; levels the
    catalogue sets no requirements for are left out. With SOFTWARE, only that vendor's rules,
    each with every field and the column answering it.
    """
    try:
        coverage = rule_coverage(catalogue)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if software is not None:
        known = sorted(set(coverage.get_column("software").to_list()))
        coverage = coverage.filter(pl.col("software").str.to_lowercase() == software.lower())
        if coverage.is_empty():
            print(
                f"{catalogue} has no rule of {software!r}; software: {', '.join(known)}",
                file=sys.stderr,
            )
            return 2
    if coverage.get_column("verdict").is_not_null().any():
        coverage = coverage.filter(pl.col("verdict").is_not_null())
    levels = coverage.group_by(["software", "version", "level"], maintain_order=True)
    for (name, version, level), rows in levels:
        print(_summary(f"{name} {version} {level}", rows))
        if software is not None:
            for row in rows.iter_rows(named=True):
                print(f"    {_field(row)}")
    return 1 if (coverage.get_column("verdict") == "fail").any() else 0


def _summary(variant: str, rows: pl.DataFrame) -> str:
    verdict = rows.get_column("verdict")[0]
    line = f"{_LABELS.get(verdict, '----')}  {variant}"
    missing = rows.filter(pl.col("column").is_null() & pl.col("requirement").is_not_null())
    if missing.is_empty():
        return line
    fields = ", ".join(
        f"{kind} {requirement}"
        for kind, requirement in missing.select("kind", "requirement").iter_rows()
    )
    return f"{line}: missing {fields}"


def _field(row: dict[str, object]) -> str:
    if row["kind"] is None:
        return "no catalogued field"
    label = str(row["kind"])
    if row["qualifiers"]:
        label += f" [{row['qualifiers']}]"
    if row["requirement"]:
        label += f" {row['requirement']}"
    if row["column"] is None:
        return f"{label}: missing"
    column = f"{row['table']}.{row['column']}" if row["table"] else str(row["column"])
    inputs = cast(list[str] | None, row["inputs"])
    if row["producer"] is None and inputs:
        column += " ← " + ", ".join(inputs)
    notes = [str(note) for note in (row["origin"], row["needs"]) if note]
    return f"{label}: {column}" + (f" ({'; '.join(notes)})" if notes else "")


def main() -> int:
    """Run the console application."""
    result = app()
    return int(result) if result is not None else 0


if __name__ == "__main__":
    sys.exit(main())
