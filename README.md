# APB Catalog

Semantic source catalogues and column resolution for APB results. Consumers ask for a meaning, such as "confidence: PEP, precursor, per run", instead of naming vendor columns such as `PEP`, `EG_PEP` or `Q_Value`.

## Use

```python
from apb_catalog.catalog import Catalog

catalog = Catalog(parsed)                                   # parsed: apb2 ParsedLevels
catalog.layer("ion", concept="confidence")                  # ('pep', 'q_value') — kinds on offer, or None
pep = catalog.layer("ion", concept="confidence", kind="pep")  # MaxQuant PEP, Spectronaut EG_PEP, DIA-NN PEP
q = catalog.var("ion", concept="confidence", kind="q_value", entity="protein_group")  # per-feature column
catalog.fields()                                            # DataFrame of every catalogued field
```

- `layer` returns the apb2 layer table, `var` the column; `None` means the vendor has no such field
- Defaults: the level's own entity, the plain value, identification confidence; override with keywords such as `statistic="max"` or `stage="quantification"`
- Two equally good fields, or a rule nobody reviewed, raise `UnresolvedField` naming the candidates
- `attach_snapshot(parsed, catalog.snapshot())` records bindings and lookups in `metadata["catalog"]`

## What is catalogued

- Vocabulary: the `confidence` concept with `kind`, `entity`, `statistic`, `direction` and `stage`; per run versus global is where the field lives (`layer` or `var`)
- Sources: every rule APB2 packages; FragPipe, i2MassChroQ, quantms, WOMBAT-P and ProteoBench custom retain no confidence field, so their requests answer `missing`
- Binding: each entry holds for the reviewed effective-rule fingerprints (SHA-256 of canonical `rule_json`); any APB2 rule change needs re-review, enforced by the drift tests

## Snapshot contract

`attach_snapshot` stores `apb-catalog-resolution` 0.1 as JSON at `ParsedLevels.metadata["catalog"]`; APB2 persists it in every format, including AnnData `uns` from HDF5 result format 5. It embeds concept definitions, level bindings, retained entries and every answer, so readers need neither this package nor its catalogues. The [JSON Schema](src/apb_catalog/data/apb-catalog-resolution-0.1.schema.json) is published with the package; `make schema` regenerates it.

## Development

```bash
uv sync --group dev
make check
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

All Python commands run from the synchronized project `.venv`.
