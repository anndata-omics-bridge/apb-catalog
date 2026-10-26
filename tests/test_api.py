"""The public module other anndata_bridge packages import."""

from __future__ import annotations

from apb_catalog import api


def test_api_exports_exactly_the_approved_names() -> None:
    assert sorted(api.__all__) == [
        "Catalog",
        "DataCatalog",
        "MissingRequiredField",
        "Reference",
        "ResolutionSnapshot",
        "StaleField",
        "UnresolvedField",
        "attach_snapshot",
        "catalogue_table",
        "catalogues",
        "rule_coverage",
        "stale_levels",
        "stored_snapshot",
    ]
