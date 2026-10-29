"""The language bundle carries the packaged rules and sets, never a plugin's, and its answers."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
from apb2.api import packaged_rule_declarations
from scripts.build_bundle import build

from apb_catalog.source import packaged_descriptions
from tests.conftest import TESTS


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """One bundle, built while the toy plugin set is installed."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("apb_catalog.source._plugin_folders", lambda: {"toy": TESTS / "toy_set"})
        yield build(tmp_path_factory.mktemp("bundle") / "apb-catalog-bundle")


def _object(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text("utf-8")))


def _rows(path: Path) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], json.loads(path.read_text("utf-8")))


def test_the_manifest_lists_every_file_the_bundle_holds(bundle: Path) -> None:
    """A reader can check the bundle is complete."""
    manifest = _object(bundle / "manifest.json")
    held = sorted(
        path.relative_to(bundle).as_posix()
        for path in bundle.rglob("*")
        if path.is_file() and path != bundle / "manifest.json"
    )
    assert manifest["files"] == held
    assert manifest["bundle_format"] == 1


def test_a_plugin_set_never_enters_the_bundle(bundle: Path) -> None:
    """Only the packaged sets are carried, in files and in expected answers."""
    packaged = list(packaged_descriptions())
    assert _object(bundle / "manifest.json")["catalogues"] == packaged
    assert sorted(path.name for path in (bundle / "catalogues" / "sources").iterdir()) == sorted(
        name for name in packaged if (bundle / "catalogues" / "sources" / name).is_dir()
    )
    assert "toy" not in (bundle / "catalogues" / "catalogues.json").read_text("utf-8")
    tables = _object(bundle / "cases" / "tables.json")
    assert [row["catalogue"] for row in tables["catalogues"]] == packaged
    cases = _rows(bundle / "cases" / "data_catalog.json")
    assert {case["catalogue"] for case in cases} == set(packaged)


def test_the_declarations_keep_apb2s_order(bundle: Path) -> None:
    """A Catalog takes a level's first declaration, so their order is part of the contract."""
    declared = _rows(bundle / "rules" / "declarations.json")
    assert [(row["rule"], row["level"]) for row in declared] == list(packaged_rule_declarations())
    assert [tuple(row["declarations"]) for row in declared] == list(
        packaged_rule_declarations().values()
    )


def test_every_outcome_is_among_the_expected_answers(bundle: Path) -> None:
    """The cases exercise each way a lookup can end."""
    cases = _rows(bundle / "cases" / "data_catalog.json")
    outcomes = {
        request["outcome"].get("error") or request["outcome"].get("warning") or "answer"
        for case in cases
        for request in case.get("requests", [])
    }
    assert outcomes == {"answer", "UnresolvedField", "StaleField", "MissingRequiredField"}
