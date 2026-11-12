"""Command line: list the sets, check the packaged APB2 rules against one, and print one as a
table across every quantification tool."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

import polars as pl
from cyclopts import App

from apb_catalog.api import catalog_table, rule_coverage, sets

app = App(
    name="apb-catalog",
    help="List APB catalog sets, check the packaged APB2 rules against one, and print one as a table",
    help_on_error=True,
)

_LABELS = {"fail": "FAIL", "warn": "WARN", "pass": "PASS"}


@app.default
def overview() -> int:
    """List every set, its prefix, its entries, and whether it sets requirements."""
    for row in sets().iter_rows(named=True):
        checked = "requirements" if row["has_requirements"] else "coverage only"
        print(f"{row['set']} ({row['prefix']}:): {row['entries']} entries, {checked}")
        print(f"    {row['purpose']}")
    return 0


@app.command
def check(set_name: str, software: str | None = None, /) -> int:
    """Check every packaged rule level against SET_NAME; exit 1 when one misses a required field.

    Each line is FAIL, WARN or PASS with the rule level and its unsupported fields; levels the
    set sets no requirements for are left out, and a set without any requirements prints ----
    for every level. With SOFTWARE, only that software's rules, each with every field and the
    name of the field answering it.
    """
    try:
        coverage = rule_coverage(set_name)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if software is not None:
        known = sorted(set(coverage.get_column("software").to_list()))
        coverage = coverage.filter(pl.col("software").str.to_lowercase() == software.lower())
        if coverage.is_empty():
            print(
                f"{set_name} has no rule of {software!r}; software: {', '.join(known)}",
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


@app.command
def meaning(
    set_name: str,
    /,
    *,
    software: str | None = None,
    software_version: str | None = None,
    format: Literal["text", "csv"] = "text",
) -> int:
    """Print SET_NAME as one table: the field holding each cataloged meaning per rule level.

    One row per packaged rule level and field: software, version label, level, slot, varm table,
    name (``none`` where the level has no field for it), key, kind, one ``qualifier.<name>``
    column per other qualifier of the set, and the app that writes the field, if any. With
    ``--software`` and ``--software-version``, only the rule levels whose version pattern
    admits that version. With ``--format csv``, the same rows as CSV.
    """
    if (software is None) != (software_version is None):
        print("--software and --software-version go together", file=sys.stderr)
        return 2
    try:
        coverage = rule_coverage(set_name)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if software is not None and software_version is not None:
        coverage = coverage.filter(
            (pl.col("software").str.to_lowercase() == software.lower())
            & pl.lit(software_version).str.contains(pl.col("software_version_pattern"))
        )
        if coverage.is_empty():
            print(
                f"no packaged {software} rule admits version {software_version!r}", file=sys.stderr
            )
            return 2
    table = _meanings(coverage)
    if format == "csv":
        sys.stdout.write(table.write_csv())
    else:
        print(_aligned(table))
    return 0


@app.command
def table(set_name: str | None = None, /, *, output: Path | None = None) -> int:
    """Write the whole catalog, or SET_NAME alone, as one long CSV table.

    One row per entry and software version it applies to: set, source, version, software version
    pattern, level, slot, table, name, key, kind, one ``qualifier.<name>`` column per other
    qualifier, requirement and entry id. Written to standard output, or to ``--output``.
    """
    try:
        rows = catalog_table(set_name)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if output is None:
        sys.stdout.write(rows.write_csv())
    else:
        rows.write_csv(output)
    return 0


def _meanings(coverage: pl.DataFrame) -> pl.DataFrame:
    """Software, version, level, slot, table, name, key and kind, one column per other
    qualifier, then the app that writes the field."""
    qualifiers = [name for name in coverage.columns if name.startswith("qualifier.")]
    return coverage.select(
        "software",
        "version",
        "level",
        "slot",
        "table",
        pl.col("name").fill_null("none"),
        "key",
        "kind",
        *qualifiers,
        "producer",
    )


def _aligned(table: pl.DataFrame) -> str:
    """Header and rows, each column padded to its widest cell; null cells stay empty."""
    rows = [table.columns] + [
        ["" if cell is None else str(cell) for cell in row] for row in table.iter_rows()
    ]
    widths = [max(len(row[index]) for row in rows) for index in range(table.width)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        for row in rows
    )


def _summary(variant: str, rows: pl.DataFrame) -> str:
    verdict = rows.get_column("verdict")[0]
    line = f"{_LABELS.get(verdict, '----')}  {variant}"
    missing = rows.filter(pl.col("name").is_null() & pl.col("requirement").is_not_null())
    if missing.is_empty():
        return line
    fields = ", ".join(
        f"{key} {requirement}"
        for key, requirement in missing.select("key", "requirement").iter_rows()
    )
    return f"{line}: missing {fields}"


def _field(row: dict[str, object]) -> str:
    if row["key"] is None:
        return "no cataloged field"
    label = str(row["key"])
    pairs = sorted(
        f"{name.removeprefix('qualifier.')}={value}"
        for name, value in row.items()
        if name.startswith("qualifier.") and value is not None
    )
    if pairs:
        label += f" [{';'.join(pairs)}]"
    if row["requirement"]:
        label += f" {row['requirement']}"
    if row["name"] is None:
        return f"{label}: missing"
    name = f"{row['table']}.{row['name']}" if row["table"] else str(row["name"])
    notes = [str(note) for note in (row["producer"], row["needs"]) if note]
    return f"{label}: {name}" + (f" ({'; '.join(notes)})" if notes else "")


def main() -> int:
    """Run the console application."""
    result = app()
    return int(result) if result is not None else 0


if __name__ == "__main__":
    sys.exit(main())
