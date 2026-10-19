"""The Catalogues page's generated tables must match the packaged catalogues."""

from __future__ import annotations

from scripts.coverage_tables import PAGE, render


def test_the_catalogue_page_matches_the_generator() -> None:
    """Regenerate with ``make docs-tables`` after changing a catalogue."""
    page = PAGE.read_text("utf-8")
    assert render(page) == page, "the Catalogues page is stale; run `make docs-tables`"
