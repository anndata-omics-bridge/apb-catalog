# APB Catalog

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23151456.svg)](https://doi.org/10.5281/zenodo.23151456)
[![PyPI](https://img.shields.io/pypi/v/apb-catalog.svg)](https://pypi.org/project/apb-catalog/)

APB Catalog finds APB result fields by reviewed meaning, one catalogue set per consumer, so the consumer asks for a meaning instead of vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

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
```

- [Every entry](https://anndata-omics-bridge.github.io/apb-catalog/catalogues/) of every packaged set
- `layer` returns the apb2 layer table, `var` the column; `None` means the vendor has no such field
- A level answers only for its own entity: ion for precursors, protein for protein groups
- Confidence lookups mean identification unless `stage="quantification"` says otherwise
- Two equally good fields, or a rule nobody reviewed, raise `UnresolvedField` naming the candidates
- A field a later producer such as apb-fasta writes raises `UnresolvedField` until that producer has run, naming what to run; `var` reads feature-aligned `varm` tables too
- Where two origins answer one kind, the set's `origin` qualifier chooses
- `attach_snapshot(parsed, catalog.snapshot())` records bindings and lookups in `metadata["catalog"][<catalogue>]["result"]`, and each level's request counts in its `metadata["catalog"][<catalogue>]["summary"]`

## Rule check

```bash
apb-catalog                          # every catalogue set
apb-catalog check SET                # FAIL, WARN or PASS per packaged rule level; exit 1 on a FAIL
apb-catalog check SET spectronaut    # one vendor, with every field and its column
```

- `rule_coverage(SET)` returns the same check as a Polars frame, one row per field
- A level fails when it misses a MUST field and warns when it misses a SHOULD or MAY one; a set's requirements set them, and a set without requirements reports coverage only

## Catalogues

- `abundance`: what each layer APB2 marks with the role `abundance` measures (intensity, MS1 intensity, MaxLFQ, iBAQ, directLFQ) and whether the software normalises it across runs (`none`, `run_setting`); used by apb-proteobench modules that ask for an un-normalised layer; 46 entries
- `identification_confidence`: how likely each identification is correct: per-run PEP and q-value layers, per-feature PEP, Sage's MS1-peak q-value, and DIA-NN's, Spectronaut's and MaxQuant's protein-group q-values; used by apb-aggregate's confidence-weighted rollups and apb-export's prolfqua target; 19 entries
- `proteobench_entrapment`: run, library and experiment-wide precursor q-values, each its own kind; used by apb-proteobench's entrapment scoring; 7 entries
- `Catalog(parsed, name).description`: the set's purpose and users, also embedded in its snapshot
- Each set lists every packaged APB2 rule level, so a vendor without a relevant field answers `missing`; `unknown` comes from an unreviewed rule or from an entry whose evidence leaves a qualifier `unknown`
- A level binds by the software name and version pattern its APB2 rule declares, plus the level; editing a rule within a version keeps its entries, and a new rule version needs its own variant
- Vocabulary: `confidence` with `kind` (pep, q_value) and `stage`; `abundance` with `kind` and `normalisation`
- Plugin sets: an installed package adds a set through the `apb_catalog.catalogues` entry-point group; [Maintaining](https://anndata-omics-bridge.github.io/apb-catalog/maintaining/#plugin-sets) describes its folder

## Snapshot contract

`attach_snapshot` stores `apb-catalog-resolution` 0.4 as JSON at `ParsedLevels.metadata["catalog"][<catalogue>]["result"]`; APB2 persists it in every format, including AnnData `uns` from HDF5 result format 6. Each level's record of the same name summarizes the resolved, missing and unresolved requests for that level. It embeds the set's description, concept definitions, level bindings, retained entries and every answer, so readers need neither this package nor its catalogues. The [JSON Schema](https://github.com/anndata-omics-bridge/apb-catalog/blob/main/src/apb_catalog/data/apb-catalog-resolution-0.4.schema.json) is published with the package; `make schema` regenerates it.

## Development

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
