"""The language bundle carries the packaged sets and rule levels, never a plugin's; its test bundle the
answers."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Iterator
from importlib import resources
from pathlib import Path
from typing import Any, cast

import pytest
from scripts.build_bundle import build

from apb_catalog.source import TABLES, packaged_descriptions
from tests.conftest import TESTS


@pytest.fixture(scope="module")
def bundles(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[Path, Path]]:
    """The bundle and its test bundle, built while the toy plugin set is installed."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("apb_catalog.source._plugin_folders", lambda: {"toy": TESTS / "toy_set"})
        yield build(tmp_path_factory.mktemp("build"))


@pytest.fixture(scope="module")
def bundle(bundles: tuple[Path, Path]) -> Path:
    return bundles[0]


@pytest.fixture(scope="module")
def test_bundle(bundles: tuple[Path, Path]) -> Path:
    return bundles[1]


def _object(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text("utf-8")))


def _rows(path: Path) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(path.read_text("utf-8")))


def _held(folder: Path) -> list[str]:
    return sorted(
        path.relative_to(folder).as_posix()
        for path in folder.rglob("*")
        if path.is_file() and path != folder / "manifest.json"
    )


def test_the_manifest_lists_every_file_each_bundle_holds(bundles: tuple[Path, Path]) -> None:
    """A reader can check a bundle is complete."""
    for folder in bundles:
        manifest = _object(folder / "manifest.json")
        assert manifest["files"] == _held(folder)
        assert manifest["bundle_format"] == 4


def test_the_bundle_holds_only_what_a_lookup_reads(bundle: Path, test_bundle: Path) -> None:
    """The served bundle holds the catalogue tables, ``versions.csv`` among them; the
    answers and synthetic results go to the test bundle."""
    assert {path.split("/")[0] for path in _held(bundle)} == {"catalogues"}
    assert {path.split("/")[0] for path in _held(test_bundle)} == {"cases", "results.tar.gz"}
    assert (
        _object(bundle / "manifest.json")["version"]
        == _object(test_bundle / "manifest.json")["version"]
    )


def test_a_plugin_set_never_enters_the_bundle(bundle: Path, test_bundle: Path) -> None:
    """Only the packaged sets are carried, in files and in expected answers."""
    packaged = list(packaged_descriptions())
    assert _object(bundle / "manifest.json")["catalogues"] == packaged
    for table in TABLES:
        text = (bundle / "catalogues" / f"{table}.csv").read_text("utf-8")
        assert {row["set"] for row in csv.DictReader(io.StringIO(text))} <= set(packaged)
    tables = _object(test_bundle / "cases" / "tables.json")
    assert [row["catalogue"] for row in tables["catalogues"]] == packaged
    cases = _rows(test_bundle / "cases" / "data_catalog.json")
    assert {case["catalogue"] for case in cases} == set(packaged)


def test_the_bundle_carries_the_packaged_versions(bundle: Path) -> None:
    """Readers turn a result's version pattern into the label entries name with the table the
    build wrote."""
    packaged = resources.files("apb_catalog").joinpath("data", "versions.csv")
    assert (bundle / "catalogues" / "versions.csv").read_text("utf-8") == packaged.read_text(
        "utf-8"
    )


def test_every_outcome_is_among_the_expected_answers(test_bundle: Path) -> None:
    """The cases exercise each way a lookup can end, and each way opening a catalog can: a set
    that answers nothing, a missing required field, a warning for a recommended one."""
    cases = _rows(test_bundle / "cases" / "data_catalog.json")
    outcomes = {
        request["outcome"].get("error") or "answer"
        for case in cases
        for request in case.get("requests", [])
    }
    assert outcomes == {"answer", "UnresolvedField"}
    opened = {case.get("error") or case.get("warning") or "opened" for case in cases}
    assert opened == {"opened", "ValueError", "MissingRequiredField"}
    assert any(case.get("warning") == "MissingRequiredField" for case in cases)
