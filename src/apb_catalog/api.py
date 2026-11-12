"""The public APB Catalog module: semantic lookups and their stored snapshots.

`apb_catalog.api_pandas` beside it holds the pandas `DataCatalog`, on the AnnData or MuData
object APB2 wrote. Installed plugins add sets through the `apb_catalog.sets` entry-point group.
"""

from __future__ import annotations

from apb_catalog.catalog import (
    Catalog,
    DataCatalog,
    MissingRequiredField,
    attach_snapshot,
)
from apb_catalog.coverage import rule_coverage, sets
from apb_catalog.resolver import UnresolvedField
from apb_catalog.snapshot import ResolutionSnapshot
from apb_catalog.table import catalog_table

__all__ = [
    "Catalog",
    "DataCatalog",
    "MissingRequiredField",
    "ResolutionSnapshot",
    "UnresolvedField",
    "attach_snapshot",
    "catalog_table",
    "rule_coverage",
    "sets",
]
