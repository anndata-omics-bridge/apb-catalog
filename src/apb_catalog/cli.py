"""Command line: list the catalogues, check the packaged APB2 rules against one, and print one
as a table across every quantification tool."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Literal, cast

import polars as pl
from cyclopts import App

from apb_catalog.api import Catalog, catalogue_table, catalogues, rule_coverage

app = App(
    name="apb-catalog",
    help="List APB catalogues, check the packaged APB2 rules against one, and print one as a table",
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
    catalogue sets no requirements for are left out, and a catalogue without any requirements
    prints ---- for every level. With SOFTWARE, only that vendor's rules, each with every field
    and the column answering it.
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


@app.command
def meaning(
    catalogue: str,
    /,
    *,
    software: str | None = None,
    version: str | None = None,
    format: Literal["text", "csv"] = "text",
) -> int:
    """Print CATALOGUE as one table: the column holding each catalogued meaning per rule level.

    One row per packaged rule level and field, with its kind and the catalogue's qualifiers;
    ``none`` where the level has no column for it. With ``--software`` and ``--version``, only
    the fields that software version's packaged rule declares. With ``--format csv``, the same
    rows as CSV.
    """
    if (software is None) != (version is None):
        print("--software and --version go together", file=sys.stderr)
        return 2
    try:
        if software is not None and version is not None:
            fields = Catalog(software, version, catalogue).fields()
            qualifiers = [name for name in fields.columns if name.startswith("qualifier.")]
            table = fields.select("level", "location", "table", "name", *qualifiers)
        else:
            table = _meanings(rule_coverage(catalogue))
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if format == "csv":
        sys.stdout.write(table.write_csv())
    else:
        print(_aligned(table))
    return 0


@app.command
def table(catalogue: str | None = None, /, *, output: Path | None = None) -> int:
    """Write every catalogue set, or CATALOGUE alone, as one long CSV table.

    One row per entry and rule it applies to: set, source, version pattern, rule, level,
    location, table, name, one ``qualifier.<name>`` column per qualifier, requirement and entry
    id. Written to standard output, or to ``--output``.
    """
    try:
        rows = catalogue_table(catalogue)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if output is None:
        sys.stdout.write(rows.write_csv())
    else:
        rows.write_csv(output)
    return 0


def _meanings(coverage: pl.DataFrame) -> pl.DataFrame:
    """Software, version, level, column and kind, then one column per qualifier of the set."""
    pairs = cast(list[str], coverage.get_column("qualifiers").drop_nulls().to_list())
    names = sorted({pair.split("=", 1)[0] for text in pairs for pair in text.split(";")})
    qualifiers = [
        pl.col("qualifiers").str.extract(rf"(?:^|;){re.escape(name)}=([^;]*)").alias(name)
        for name in names
    ]
    if coverage.get_column("origin").is_not_null().any():
        qualifiers.append(pl.col("origin"))
    column = (
        pl.when(pl.col("table").is_not_null())
        .then(pl.concat_str(pl.col("table"), pl.lit("."), pl.col("column")))
        .otherwise(pl.col("column"))
    )
    column = (
        pl.when(pl.col("producer").is_not_null())
        .then(pl.concat_str(column, pl.lit(" ("), pl.col("producer"), pl.lit(")")))
        .otherwise(column)
    )
    return coverage.select(
        "software",
        "version",
        "level",
        column.fill_null("none").alias("column"),
        "kind",
        *qualifiers,
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
