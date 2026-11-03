"""APB Catalog's pandas API: the catalog on the AnnData or MuData object APB2 wrote.

The one module beside :mod:`apb_catalog.api`; every other name, such as ``UnresolvedField``,
comes from there.
"""

from __future__ import annotations

from apb_catalog.anndata_catalog import DataCatalog

__all__ = ["DataCatalog"]
