# APB Catalog

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23151456.svg)](https://doi.org/10.5281/zenodo.23151456)
[![PyPI](https://img.shields.io/pypi/v/apb-catalog.svg)](https://pypi.org/project/apb-catalog/)

Catalogues of what APB result fields mean, one set per kind of meaning, each stating its purpose and users, so the consumer asks for a meaning instead of vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

Documentation: [anndata-omics-bridge.github.io/apb-catalog](https://anndata-omics-bridge.github.io/apb-catalog/), built from [docs/](https://github.com/anndata-omics-bridge/apb-catalog/tree/main/docs) with `make docs`; start with [Get started](https://anndata-omics-bridge.github.io/apb-catalog/getting-started/).

## Installation

```bash
pip install apb-catalog
```

## Use

```python
from apb_catalog.api import Catalog

confidence = Catalog(parsed, "identification_confidence")                     # parsed: apb2 ParsedLevels
confidence.layer("ion", concept="confidence")                 # ('pep', 'q_value') — kinds on offer, or None
pep = confidence.layer("ion", concept="confidence", kind="pep")  # MaxQuant PEP, Spectronaut EG_PEP, DIA-NN PEP

miape = Catalog(parsed, "miape")
miape.var("protein", concept="miape")                        # ('gene_name', 'protein_group')
genes = miape.var("protein", concept="miape", kind="gene_name")  # the column MIAPE-AnnData calls gene_name
```

- [Every entry](https://anndata-omics-bridge.github.io/apb-catalog/catalogues/) of both sets
- `layer` returns the apb2 layer table, `var` the column; `None` means the vendor has no such field
- A level answers only for its own entity: ion for precursors, protein for protein groups
- Confidence lookups mean identification unless `stage="quantification"` says otherwise
- Two equally good fields, or a rule nobody reviewed, raise `UnresolvedField` naming the candidates
- `attach_snapshot(parsed, catalog.snapshot())` records bindings and lookups in `metadata["catalog"][<catalogue>]`

## Catalogues

- `identification_confidence`: how likely each identification is correct: per-run PEP and q-value layers, per-feature PEP, Sage's MS1-peak q-value, and DIA-NN's and Spectronaut's protein-group q-values; used by apb-aggregate's confidence-weighted rollups and apb-export's prolfqua target; 18 entries
- `miape`: draft mapping onto the MIAPE-AnnData Schema 0.4.0 draft (HUPO-PSI AI Readiness Working Group): protein, peptide and peptidoform fields and the `raw` layer; ion levels have no MIAPE modality; 32 entries
- `Catalog(parsed, name).description`: the set's purpose and users, also embedded in its snapshot
- Each set lists every packaged APB2 rule level, so a vendor without a relevant field answers `missing`, never `unknown`
- A level binds by the software name and version pattern its APB2 rule declares, plus the level; editing a rule within a version keeps its entries, and a new rule version needs its own variant
- Vocabulary: `confidence` with `kind` (pep, q_value) and `stage`; `miape` with `kind` naming the MIAPE-AnnData field and its requirement level

## Snapshot contract

`attach_snapshot` stores `apb-catalog-resolution` 0.3 as JSON at `ParsedLevels.metadata["catalog"][<catalogue>]`; APB2 persists it in every format, including AnnData `uns` from HDF5 result format 5. It embeds the set's description, concept definitions, level bindings, retained entries and every answer, so readers need neither this package nor its catalogues. The [JSON Schema](https://github.com/anndata-omics-bridge/apb-catalog/blob/main/src/apb_catalog/data/apb-catalog-resolution-0.3.schema.json) is published with the package; `make schema` regenerates it.

## Development

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
