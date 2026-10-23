"""A synthetic plugin set, installed as if a package registered it."""

from __future__ import annotations

from pathlib import Path

import pytest

TESTS = Path(__file__).parent


@pytest.fixture
def toy_set(monkeypatch: pytest.MonkeyPatch) -> str:
    """Register ``tests/toy_set`` as the plugin set ``toy``; its loaded set stays cached."""
    monkeypatch.setattr("apb_catalog.source._plugin_folders", lambda: {"toy": TESTS / "toy_set"})
    return "toy"


@pytest.fixture
def two_concept_set(monkeypatch: pytest.MonkeyPatch) -> str:
    """Register ``tests/two_concept_set`` as the plugin set ``two_concepts``."""
    monkeypatch.setattr(
        "apb_catalog.source._plugin_folders",
        lambda: {"two_concepts": TESTS / "two_concept_set"},
    )
    return "two_concepts"
