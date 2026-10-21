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
