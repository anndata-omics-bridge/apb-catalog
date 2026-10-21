"""The command line lists the catalogues and checks the packaged rules against one."""

from __future__ import annotations

import pytest

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
    assert "identification_confidence: 19 entries, coverage only" in output


def test_check_fails_when_a_level_misses_a_must_field(
    toy_set: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """FragPipe names no protein group, so the check exits 1."""
    assert _run("check", toy_set) == 1
    output = capsys.readouterr().out
    assert "FAIL  FragPipe 22\u201323 ion: missing group MUST" in output
    assert "PASS  DIA-NN 2.x ion" in output


def test_a_set_without_requirements_never_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """Coverage-only sets list their levels without a verdict."""
    assert _run("check", "identification_confidence") == 0
    assert "----  DIA-NN 2.x ion" in capsys.readouterr().out


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


@pytest.mark.parametrize(
    "argv", [("check", "nope"), ("check", "identification_confidence", "nope")]
)
def test_unknown_names_exit_2(argv: tuple[str, ...], capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown set or software names what exists."""
    assert _run(*argv) == 2
    assert "identification_confidence" in capsys.readouterr().err
