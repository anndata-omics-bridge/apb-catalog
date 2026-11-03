"""The public modules other anndata_bridge packages import: api, and api_pandas beside it."""

from __future__ import annotations

from apb_catalog import api, api_pandas


def test_api_exports_exactly_the_approved_names() -> None:
    assert sorted(api.__all__) == [
        "Catalog",
        "DataCatalog",
        "MissingRequiredField",
        "ResolutionSnapshot",
        "UnresolvedField",
        "attach_snapshot",
        "catalogue_table",
        "catalogues",
        "rule_coverage",
    ]


def test_the_pandas_api_exports_only_its_data_catalog() -> None:
    assert api_pandas.__all__ == ["DataCatalog"]
