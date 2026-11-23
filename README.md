# APB Catalog

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23151456.svg)](https://doi.org/10.5281/zenodo.23151456)
[![PyPI](https://img.shields.io/pypi/v/apb-catalog.svg)](https://pypi.org/project/apb-catalog/)

APB Catalog finds APB result fields by reviewed meaning, so a consumer asks for a meaning instead of vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

Documentation: [anndata-omics-bridge.github.io/apb-catalog](https://anndata-omics-bridge.github.io/apb-catalog/)

Try it online:

- [Rules viewer](https://fgcz-ms.uzh.ch/public/apb-rules/): every vendor table's parse rules, as apb2 packages them
- [Catalog viewer](https://fgcz-ms.uzh.ch/public/apb-catalog/): every catalog set with its entries and coverage
- [APB Studio](https://fgcz-ms.uzh.ch/public/apb-studio/): APB's corpus runs over the test vendor files
- [APB Export](https://apps-dev.bfabric.org/apb-export/): convert a vendor table for a downstream tool in the browser

| Page | For |
| --- | --- |
| [Get started](https://anndata-omics-bridge.github.io/apb-catalog/getting-started/) | Install, look up fields, use the data |
| [Sets](https://anndata-omics-bridge.github.io/apb-catalog/sets/) | Every set: its vocabulary, which software has which field |
| [Python API](https://anndata-omics-bridge.github.io/apb-catalog/api/) | Every call, answer, table and command |
| [Maintaining](https://anndata-omics-bridge.github.io/apb-catalog/maintaining/) | APB2 rule changes, new sets, the checks |
| [Contributing](https://anndata-omics-bridge.github.io/apb-catalog/contributing/) | Extend a set, or create your own |

## Install

```bash
pip install apb-catalog
```

The default install supports name lookups and HDF5 results (`.h5ad` and `.h5mu`). APB2 can pass DuckDB and Parquet results to `DataCatalog` through `read_parsed_levels`. Install `apb2[duckdb]` to use DuckDB. Install `apb2[excel]` when converting MSAngel or ProlineStudio workbooks with APB2.

## Use

```python
from apb_catalog.api import DataCatalog

ion = DataCatalog(parsed, "confidence").levels["peptidoform_ion"]  # parsed: an apb2 ParsedLevels result
ion.layers.keys()                  # {'pep', 'q_value'}
pep = ion.layers.get("pep")        # runs × ions, numpy; None when the vendor reports no PEP
ion.layers.name("pep")             # MaxQuant 'PEP', Spectronaut 'EG_PEP', DIA-NN 'PEP'
```

With pandas, on the MuData or AnnData object APB2 wrote, the same keys return AnnData's own matrices and pandas Series: `from apb_catalog.api_pandas import DataCatalog`, then `DataCatalog(mdata, "confidence_alpha")`; see [pandas](https://anndata-omics-bridge.github.io/apb-catalog/api/#pandas).

```bash
apb-catalog                       # every set
apb-catalog check SET_NAME        # FAIL, WARN or PASS per packaged rule level; ---- for a set without requirements
```

## Development

`uv sync` installs apb2 from a sibling checkout at `../apb2` (`[tool.uv.sources]` in `pyproject.toml`); clone [apb2](https://github.com/anndata-omics-bridge/apb2) next to this repository first.

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
