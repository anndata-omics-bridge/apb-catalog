# APB Catalog

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23151456.svg)](https://doi.org/10.5281/zenodo.23151456)
[![PyPI](https://img.shields.io/pypi/v/apb-catalog.svg)](https://pypi.org/project/apb-catalog/)

APB Catalog finds APB result fields by reviewed meaning, so a consumer asks for a meaning instead of vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

Documentation: [anndata-omics-bridge.github.io/apb-catalog](https://anndata-omics-bridge.github.io/apb-catalog/)

Catalog viewer: [fgcz-ms.uzh.ch/public/apb-catalog](https://fgcz-ms.uzh.ch/public/apb-catalog/), every catalogue set with its entries, requirements and coverage, in the browser.

| Page | For |
| --- | --- |
| [Get started](https://anndata-omics-bridge.github.io/apb-catalog/getting-started/) | Install, look up fields, use the data |
| [Catalogues](https://anndata-omics-bridge.github.io/apb-catalog/catalogues/) | Every set: its vocabulary, which software has which field |
| [Python API](https://anndata-omics-bridge.github.io/apb-catalog/api/) | Every call, answer, table and command |
| [Maintaining](https://anndata-omics-bridge.github.io/apb-catalog/maintaining/) | APB2 rule changes, new sets, the checks |
| [Contributing](https://anndata-omics-bridge.github.io/apb-catalog/contributing/) | Extend a catalog, or create your own |

## Install

```bash
pip install apb-catalog
```

## Use

```python
from apb_catalog.api import DataCatalog

ion = DataCatalog(parsed, "confidence").levels["peptidoform_ion"]  # parsed: an apb2 ParsedLevels result
ion.layers.keys()                  # {'pep', 'q_value'}
pep = ion.layers.get("pep")        # runs × ions, numpy; None when the vendor reports no PEP
ion.layers.name("pep")             # MaxQuant 'PEP', Spectronaut 'EG_PEP', DIA-NN 'PEP'
```

With pandas, on the MuData or AnnData object APB2 wrote, the same keys return AnnData's own matrices and pandas Series: `from apb_catalog.api_pandas import DataCatalog`, then `DataCatalog(mdata, "confidence")`; see [pandas](https://anndata-omics-bridge.github.io/apb-catalog/api/#pandas).

```bash
apb-catalog                       # every set
apb-catalog check SET             # FAIL, WARN or PASS per packaged rule level; ---- for a set without requirements
```

## Development

`uv sync` installs apb2 from a sibling checkout at `../apb2` (`[tool.uv.sources]` in `pyproject.toml`); clone [apb2](https://github.com/anndata-omics-bridge/apb2) next to this repository first.

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
