"""The command line lists the sets, checks the packaged rules against one, and prints one
as a table."""

from __future__ import annotations

import io

import polars as pl
import pytest

from apb_catalog.api import rule_coverage
from apb_catalog.cli import app


def _run(*argv: str) -> object:
    return app(list(argv), exit_on_error=False, result_action="return_value")


def test_without_arguments_every_set_is_listed(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """One line per set, packaged or plugin, saying whether it sets requirements."""
    assert _run() == 0
    output = capsys.readouterr().out
    assert f"{toy_set} (toy:): 22 entries, requirements" in output
    assert "confidence_alpha (c:): 26 entries, coverage only" in output


def test_check_fails_when_a_level_misses_a_required_field(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """FragPipe names no protein group, so the check exits 1."""
    assert _run("check", toy_set) == 1
    output = capsys.readouterr().out
    assert "FAIL  FragPipe 22\u201323 peptidoform_ion: missing group required" in output
    assert "PASS  DIA-NN 2.x peptidoform_ion" in output


def test_a_set_without_requirements_never_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """Coverage-only sets list their levels without a verdict."""
    assert _run("check", "confidence_alpha") == 0
    assert "----  DIA-NN 2.x peptidoform_ion" in capsys.readouterr().out


def test_software_shows_every_field_and_its_column(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The vendor's own fields, their qualifiers, the app that writes one and what to run."""
    _run("check", toy_set, "fragpipe")
    output = capsys.readouterr().out
    assert "charge [origin=vendor] required: Charge" in output
    assert "decoy [origin=vendor] optional: apb_Decoy" in output
    assert "group required: missing" in output
    assert "(apb-fasta; run `apb-fasta verify-peptides`)" in output
    assert "DIA-NN" not in output


MEANING = ["software", "version", "level", "slot", "table", "name", "key", "kind"]


def test_meaning_prints_the_field_of_every_meaning_per_rule_level(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """One row per rule level and field, with its key, kind and the set's qualifiers as columns."""
    assert _run("meaning", "abundance_alpha") == 0
    lines = capsys.readouterr().out.splitlines()
    qualifiers = ["qualifier.normalization", "qualifier.aggregation", "qualifier.ms_level"]
    assert lines[0].split() == [*MEANING, *qualifiers, "producer"]
    row = ["DIA-NN", "2.x", "peptidoform_ion", "layers", "Precursor_Normalised"]
    expected = [*row, "intensity_norm_settings", "intensity", "run_setting", "none", "ms2"]
    assert expected in [line.split() for line in lines]


def test_meaning_writes_the_same_rows_as_csv(capsys: pytest.CaptureFixture[str]) -> None:
    """CSV has the text table's columns and one row per field of the rule check."""
    assert _run("meaning", "abundance_alpha", "--format", "csv") == 0
    table = pl.read_csv(io.StringIO(capsys.readouterr().out))
    assert table.columns == [
        *MEANING,
        "qualifier.normalization",
        "qualifier.aggregation",
        "qualifier.ms_level",
        "producer",
    ]
    assert table.height == rule_coverage("abundance_alpha").height


def test_meaning_narrows_to_one_software_version(capsys: pytest.CaptureFixture[str]) -> None:
    """``--software`` and ``--software-version`` keep the rule levels admitting that version."""
    argv = ("meaning", "abundance_alpha", "--software", "dia-nn", "--software-version", "2.6.0")
    assert _run(*argv, "--format", "csv") == 0
    table = pl.read_csv(io.StringIO(capsys.readouterr().out))
    assert set(table.get_column("version")) == {"2.x"}
    assert "Precursor_Quantity" in table.get_column("name").to_list()


def test_a_level_without_an_entry_names_none(capsys: pytest.CaptureFixture[str]) -> None:
    """A rule level the set has no entry for still gets a row, its name ``none``."""
    _run("meaning", "confidence_alpha", "--format", "csv")
    table = pl.read_csv(io.StringIO(capsys.readouterr().out))
    assert not table.filter(pl.col("name") == "none").is_empty()


def test_meaning_names_who_writes_a_field(toy_set: str, capsys: pytest.CaptureFixture[str]) -> None:
    """A field another package writes names its producer; the toy set's origin is a qualifier."""
    _run("meaning", toy_set, "--format", "csv")
    table = pl.read_csv(io.StringIO(capsys.readouterr().out))
    assert table.columns[-2:] == ["qualifier.origin", "producer"]
    found = table.filter(pl.col("name") == "fasta_matches_contaminant")
    assert set(found.get_column("table")) == {"fasta_validation"}
    assert set(found.get_column("producer")) == {"apb-fasta"}


@pytest.mark.parametrize(
    "argv",
    [("check", "nope"), ("check", "confidence_alpha", "nope"), ("meaning", "nope")],
)
def test_unknown_names_exit_2(argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown set or software names what exists."""
    assert _run(*argv) == 2
    assert "confidence_alpha" in capsys.readouterr().err
