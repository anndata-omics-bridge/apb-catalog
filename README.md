# APB Catalog

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23151456.svg)](https://doi.org/10.5281/zenodo.23151456)
[![PyPI](https://img.shields.io/pypi/v/apb-catalog.svg)](https://pypi.org/project/apb-catalog/)

APB Catalog finds APB result fields by reviewed meaning, so a consumer asks for a meaning instead of vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

Documentation: [anndata-omics-bridge.github.io/apb-catalog](https://anndata-omics-bridge.github.io/apb-catalog/)

| Page | For |
| --- | --- |
| [Get started](https://anndata-omics-bridge.github.io/apb-catalog/getting-started/) | Install, look up fields, use the data |
| [Catalogues](https://anndata-omics-bridge.github.io/apb-catalog/catalogues/) | Every set: its vocabulary, which software has which field |
| [Python API](https://anndata-omics-bridge.github.io/apb-catalog/api/) | Every call, answer, table and command |
| [Maintaining](https://anndata-omics-bridge.github.io/apb-catalog/maintaining/) | APB2 rule changes, new sets, the checks |

## Install

```bash
pip install apb-catalog
```

## Use

```python
from apb_catalog.api import DataCatalog

confidence = DataCatalog(parsed, "confidence")             # parsed: an apb2 ParsedLevels result
confidence.kinds("peptidoform_ion", "layers")              # ('pep', 'q_value')
pep = confidence.layer("peptidoform_ion", kind="pep")      # MaxQuant PEP, Spectronaut EG_PEP, DIA-NN PEP
```

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
