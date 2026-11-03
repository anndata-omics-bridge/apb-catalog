"""The public APB Catalog module: semantic lookups and their stored snapshots.

`apb_catalog.api_pandas` beside it holds the pandas `DataCatalog`, on the AnnData or MuData
object APB2 wrote. Installed plugins add catalogue sets through the `apb_catalog.catalogues` entry-point group.
"""

from __future__ import annotations

from apb_catalog.catalog import (
    Catalog,
    DataCatalog,
    MissingRequiredField,
    attach_snapshot,
)
from apb_catalog.coverage import catalogues, rule_coverage
from apb_catalog.resolver import UnresolvedField
from apb_catalog.snapshot import ResolutionSnapshot
from apb_catalog.table import catalogue_table

__all__ = [
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
