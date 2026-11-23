"""The catalog APIs can resolve names without loading optional APB2 backends."""

from __future__ import annotations

import subprocess
import sys


def test_catalog_lookup_leaves_optional_backends_unloaded() -> None:
    command = """
import sys

from apb_catalog.api import Catalog
from apb_catalog.api_pandas import DataCatalog

ions = Catalog("DIA-NN", "2.6.0", "abundance_alpha").levels["peptidoform_ion"]
assert ions.layers["intensity"] == "Precursor_Quantity"
for name in ("duckdb", "fastexcel", "python_calamine"):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", command], check=True)
