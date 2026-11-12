"""The Sets page's generated tables must match the packaged sets."""

from __future__ import annotations

from scripts.coverage_tables import PAGE, render


def test_the_sets_page_matches_the_generator() -> None:
    """Regenerate with ``make docs-tables`` after changing a set."""
    page = PAGE.read_text("utf-8")
    assert render(page) == page, "the Sets page is stale; run `make docs-tables`"
