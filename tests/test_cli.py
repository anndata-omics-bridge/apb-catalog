"""The command line lists the catalogues and checks the packaged rules against one."""

from __future__ import annotations

import pytest

from apb_catalog.cli import app


def _run(*argv: str) -> object:
    return app(list(argv), exit_on_error=False, result_action="return_value")


def test_without_arguments_every_catalogue_is_listed(capsys: pytest.CaptureFixture[str]) -> None:
    """One line per set, saying whether it sets requirements."""
    assert _run() == 0
    output = capsys.readouterr().out
    assert "miape: 94 entries, requirements" in output
    assert "identification_confidence:" in output


def test_check_fails_when_a_level_misses_a_must_field(capsys: pytest.CaptureFixture[str]) -> None:
    assert _run("check", "miape") == 1
    output = capsys.readouterr().out
    assert "FAIL  MaxQuant 1.5, 1.6, 2.x peptidoform: missing peptidoform MUST" in output
    assert "PASS  DIA-NN 2.x ion" in output
    assert "fragment" not in output


def test_a_set_without_requirements_never_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """Coverage-only sets list their levels without a verdict."""
    assert _run("check", "identification_confidence") == 0
    assert "----  DIA-NN 2.x ion" in capsys.readouterr().out


def test_software_shows_every_field_and_its_column(capsys: pytest.CaptureFixture[str]) -> None:
    """The vendor's own columns, computed inputs, origins and what to run are all named."""
    _run("check", "miape", "spectronaut")
    output = capsys.readouterr().out
    assert "PG_ProteinGroups (vendor)" in output
    assert "apb_Decoy ← EG_IsDecoy (vendor)" in output
    assert "run `apb-fasta verify-peptides`" in output
    assert "DIA-NN" not in output


@pytest.mark.parametrize("argv", [("check", "nope"), ("check", "miape", "nope")])
def test_unknown_names_exit_2(argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown set or software names what exists."""
    assert _run(*argv) == 2
    assert "miape" in capsys.readouterr().err
