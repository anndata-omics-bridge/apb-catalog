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
from apb_catalog.api import Catalog, DataCatalog

confidence = DataCatalog(parsed, "confidence")                     # parsed: apb2 ParsedLevels
confidence.kinds("peptidoform_ion", "layers")                    # ('pep', 'q_value') — kinds on offer, () for none
pep = confidence.layer("peptidoform_ion", kind="pep")  # MaxQuant PEP, Spectronaut EG_PEP, DIA-NN PEP
```

- [Every entry](https://anndata-omics-bridge.github.io/apb-catalog/catalogues/) of every packaged set
- `layer` returns the apb2 layer table, `var` the column; `None` means the vendor has no such field, or APB2 left it out of this result because it held one value or none (the level's parse record lists it under `result.uninformative_fields`)
- `Catalog("DIA-NN", "2.6.0", "abundance")` answers column names from a software version's packaged rule, without data
- `enforce="MUST"` makes a set's MUST fields binding and warns for its SHOULD fields; `enforce="SHOULD"` makes both binding
- A level answers only for its own entity: peptidoform_ion for precursors, protein for protein groups
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
apb-catalog meaning SET              # one table: column, kind and qualifiers of every meaning per rule level
apb-catalog meaning SET --format csv # the same table as CSV
```

- `meaning` shows which quantification tools report a meaning, and in which column; `unknown` in a qualifier means the entry is reviewed but the tool's documentation does not settle it

- `rule_coverage(SET)` returns the same check as a Polars frame, one row per field
- A level fails when it misses a MUST field and warns when it misses a SHOULD or MAY one; a set's requirements set them, and a set without requirements reports coverage only

## Catalogues

- `chromatography`: observed retention time and its original unit (`second`, `minute`, or explicitly `unknown`); used by the QPX exporter; six entries cover nine retained fields across APB2 rule variants; no required RT field and no value conversion in the catalogue
- `abundance`: what each layer APB2 marks with the role `abundance` measures (intensity, MS1 intensity, MaxLFQ, iBAQ, directLFQ) and whether the software normalizes it across runs (`none`, `run_setting`); used by apb-proteobench modules that ask for an un-normalized layer; 48 entries
- `confidence`: how likely each identification is correct: per-run PEP and q-value layers, per-feature PEP, Sage's MS1-peak q-value, and DIA-NN's, Spectronaut's and MaxQuant's protein-group q-values, and DIA-NN's and Spectronaut 21's library q-values; used by apb-aggregate's confidence-weighted rollups and apb-export's prolfqua target; 22 entries
- `proteobench_entrapment`: run, library and experiment-wide precursor q-values, each its own kind; used by apb-proteobench's entrapment scoring and by apb-export's msmu `q_value` and prolfqua `qValue` fallback; 7 entries
- `apb`: the fields APB writes for every vendor, by kind: the ProForma identifiers, the decoy and contaminant flags, the var columns a rule's roles name, and a sample annotation's condition and biological replicate; requirement rows say which levels carry each; used by apb-export's export rules
- `DataCatalog(parsed, name).description` and `Catalog(software, version, name).description`: the set's purpose and users, also embedded in its snapshot
- Each set lists every packaged APB2 rule level, so a vendor without a relevant field answers `missing`; `unknown` comes from an unreviewed rule or from an entry whose evidence leaves a qualifier `unknown`
- A level binds by the software name and version pattern its APB2 rule declares, plus the level; editing a rule within a version keeps its entries, and a new rule version needs its own variant
- Vocabulary: `confidence` with `kind` (pep, q_value) and `stage`; `abundance` with `kind` and `normalization`
- Plugin sets: an installed package adds a set through the `apb_catalog.catalogues` entry-point group; [Maintaining](https://anndata-omics-bridge.github.io/apb-catalog/maintaining/#plugin-sets) describes its folder

## Snapshot contract

`attach_snapshot` stores `apb-catalog-resolution` 0.5 as JSON at `ParsedLevels.metadata["catalog"][<catalogue>]["result"]`; APB2 persists it in every format, including AnnData `uns` from HDF5 result format 6. Each level's record of the same name summarizes the resolved, missing and unresolved requests for that level. It embeds the set's description, its vocabulary, level bindings, retained entries and every answer, so readers need neither this package nor its catalogues. The [JSON Schema](https://github.com/anndata-omics-bridge/apb-catalog/blob/main/src/apb_catalog/data/apb-catalog-resolution-0.5.schema.json) is published with the package; `make schema` regenerates it.

## Development

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
