"""The one public APB Catalog module: semantic lookups and their stored snapshots.

Installed plugins add catalogue sets through the `apb_catalog.catalogues` entry-point group.
"""

from __future__ import annotations

from apb_catalog.catalog import (
    Catalog,
    DataCatalog,
    MissingRequiredField,
    Reference,
    StaleField,
    attach_snapshot,
    stale_levels,
    stored_snapshot,
)
from apb_catalog.coverage import catalogues, rule_coverage
from apb_catalog.resolver import UnresolvedField
from apb_catalog.snapshot import ResolutionSnapshot
from apb_catalog.table import catalogue_table

__all__ = [
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
