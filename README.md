# APB Catalog

Catalogues of what APB result fields mean, one set per kind of meaning, each stating its purpose and users, so the consumer asks for a meaning instead of vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

Documentation: [anndata-omics-bridge.github.io/apb-catalog](https://anndata-omics-bridge.github.io/apb-catalog/), built from [docs/](docs/) with `make docs`; start with [Get started](docs/getting-started.md).

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

- [Every entry](docs/catalogues.md) of both sets
- `layer` returns the apb2 layer table, `var` the column; `None` means the vendor has no such field
- A level answers only for its own entity: ion for precursors, protein for protein groups
- Confidence lookups mean identification unless `stage="quantification"` says otherwise
- Two equally good fields, or a rule nobody reviewed, raise `UnresolvedField` naming the candidates
- `attach_snapshot(parsed, catalog.snapshot())` records bindings and lookups in `metadata["catalog"][<catalogue>]`

## Catalogues

- `identification_confidence`: how likely each identification is correct: per-run PEP and q-value layers, per-feature PEP and Sage's MS1-peak q-value; used by apb-aggregate's confidence-weighted rollups; 12 entries
- `miape`: draft mapping onto the MIAPE-AnnData Schema 0.4.0 draft (HUPO-PSI AI Readiness Working Group): protein, peptide and peptidoform fields and the `raw` layer; ion levels have no MIAPE modality; 32 entries
- `Catalog(parsed, name).description`: the set's purpose and users, also embedded in its snapshot
- Each set lists every packaged APB2 rule level, so a vendor without a relevant field answers `missing`, never `unknown`
- Entries bind to reviewed effective-rule fingerprints (SHA-256 of canonical `rule_json`); any APB2 rule change needs re-review, enforced by the drift tests
- Vocabulary: `confidence` with `kind` (pep, q_value) and `stage`; `miape` with `kind` naming the MIAPE-AnnData field and its requirement level

## Snapshot contract

`attach_snapshot` stores `apb-catalog-resolution` 0.2 as JSON at `ParsedLevels.metadata["catalog"][<catalogue>]`; APB2 persists it in every format, including AnnData `uns` from HDF5 result format 5. It embeds the set's description, concept definitions, level bindings, retained entries and every answer, so readers need neither this package nor its catalogues. The [JSON Schema](src/apb_catalog/data/apb-catalog-resolution-0.2.schema.json) is published with the package; `make schema` regenerates it.

## Development

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
