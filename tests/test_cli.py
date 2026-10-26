"""The command line lists the catalogues, checks the packaged rules against one, and prints one
as a table."""

from __future__ import annotations

import io

import polars as pl
import pytest

from apb_catalog.api import rule_coverage
from apb_catalog.cli import app


def _run(*argv: str) -> object:
    return app(list(argv), exit_on_error=False, result_action="return_value")


def test_without_arguments_every_catalogue_is_listed(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """One line per set, packaged or plugin, saying whether it sets requirements."""
    assert _run() == 0
    output = capsys.readouterr().out
    assert f"{toy_set}: 8 entries, requirements" in output
    assert "identification_confidence: 20 entries, coverage only" in output


def test_check_fails_when_a_level_misses_a_must_field(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """FragPipe names no protein group, so the check exits 1."""
    assert _run("check", toy_set) == 1
    output = capsys.readouterr().out
    assert "FAIL  FragPipe 22\u201323 peptidoform_ion: missing group MUST" in output
    assert "PASS  DIA-NN 2.x peptidoform_ion" in output


def test_a_set_without_requirements_never_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """Coverage-only sets list their levels without a verdict."""
    assert _run("check", "identification_confidence") == 0
    assert "----  DIA-NN 2.x peptidoform_ion" in capsys.readouterr().out


def test_software_shows_every_field_and_its_column(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The vendor's own columns, computed inputs, origins and what to run are all named."""
    _run("check", toy_set, "fragpipe")
    output = capsys.readouterr().out
    assert "charge MUST: Charge (vendor)" in output
    assert "decoy MAY: apb_Decoy ← Protein (vendor)" in output
    assert "group MUST: missing" in output
    assert "(apb_fasta; run `apb-fasta verify-peptides`)" in output
    assert "DIA-NN" not in output


def test_meaning_prints_the_column_of_every_meaning_per_rule_level(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One row per rule level and field, with its kind and the set's qualifier as columns."""
    assert _run("meaning", "abundance") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["software", "version", "level", "column", "kind", "normalization"]
    assert ["DIA-NN", "2.x", "peptidoform_ion", "Precursor_Quantity", "intensity", "none"] in [
        line.split() for line in lines
    ]


def test_meaning_writes_the_same_rows_as_csv(capsys: pytest.CaptureFixture[str]) -> None:
    """CSV has the text table's columns and one row per field of the rule check."""
    assert _run("meaning", "abundance", "--format", "csv") == 0
    table = pl.read_csv(io.StringIO(capsys.readouterr().out))
    assert table.columns == ["software", "version", "level", "column", "kind", "normalization"]
    assert table.height == rule_coverage("abundance").height


def test_a_level_without_an_entry_names_none(capsys: pytest.CaptureFixture[str]) -> None:
    """A rule level the set has no entry for still gets a row, its column ``none``."""
    _run("meaning", "identification_confidence", "--format", "csv")
    table = pl.read_csv(io.StringIO(capsys.readouterr().out))
    assert not table.filter(pl.col("column") == "none").is_empty()


def test_meaning_names_who_writes_a_column(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """A column another package writes carries its producer, and the origin becomes a column."""
    _run("meaning", toy_set)
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[-1] == "origin"
    assert any("fasta_validation.fasta_matches_contaminant (apb-fasta)" in line for line in lines)


@pytest.mark.parametrize(
    "argv",
    [("check", "nope"), ("check", "identification_confidence", "nope"), ("meaning", "nope")],
)
def test_unknown_names_exit_2(argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown set or software names what exists."""
    assert _run(*argv) == 2
    assert "identification_confidence" in capsys.readouterr().err
