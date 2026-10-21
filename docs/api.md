# Python API

## Lookups

```python
from apb2.api import read_parsed_levels
from apb_catalog.api import Catalog

parsed = read_parsed_levels(path)
catalog = Catalog(parsed, "identification_confidence")
```

| Call | Returns |
| --- | --- |
| `catalog.layer(level, concept=..., kind=...)` | The apb2 `FinalLayerTable`, samples × features, or `None` |
| `catalog.var(level, concept=..., kind=...)` | The var column as a Polars `Series`, or `None` |
| `catalog.layer(level, concept=...)` | The kinds the level offers as layers, or `None` |
| `catalog.var(level, concept=...)` | The kinds the level offers as var columns, or `None` |
| `catalog.fields()` | A Polars `DataFrame` of every catalogued field the result retains |

- A level answers only for its own entity: ion for precursors, protein for protein groups
- Per run versus per feature is the choice between `layer` and `var`
- Confidence lookups mean identification; pass `stage="quantification"` for Sage's MS1-peak q-value
- `var` also reads feature-aligned `varm` tables, such as apb-fasta's `fasta_validation`
- In a set whose concept has an `origin` qualifier, `origin=...` chooses where two origins answer one kind
- Misspelled concepts, kinds or catalogue names raise `ValueError`

## When there is no single answer

`UnresolvedField` (from `apb_catalog.api`) is raised, naming the reason and the candidates, when:

- two catalogued fields fit equally well, or
- no catalogue variant names the level's software version, for example a new rule version, or a level produced by another tool, or
- the field is apb-fasta's and `apb-fasta verify-peptides` has not run; the message names that command

`None` means the result lacks the level, or its software version was reviewed and the field is not there.

## Snapshots

```python
from apb_catalog.api import attach_snapshot, stale_levels, stored_snapshot

annotated = attach_snapshot(parsed, catalog.snapshot())   # new result; data shared, not copied
stored_snapshot(annotated, "identification_confidence")                   # read it back
stale_levels(annotated, catalog.snapshot())               # levels whose software name or version changed since
```

The snapshot is stored as JSON at `metadata["catalog"][<set>]["result"]`, beside other sets' snapshots, with each level's request counts in that level's `metadata["catalog"][<set>]["summary"]`. Both persist in h5ad, h5mu, Parquet and DuckDB. It embeds the set's description, concept definitions, level bindings, catalogued fields and every answer, so a reader needs neither this package nor its catalogues. Its JSON Schema ships as `apb_catalog/data/apb-catalog-resolution-0.4.schema.json`.

## Rule check

```python
from apb_catalog.api import catalogues, rule_coverage

catalogues()             # one row per set: purpose, users, entries, whether it sets requirements
rule_coverage("identification_confidence")   # one row per field of every packaged rule level
```

| Column | Meaning |
| --- | --- |
| `software`, `version`, `rule`, `level` | The packaged APB2 rule level; `version` is the concise reading of its version pattern |
| `kind`, `qualifiers`, `origin` | The catalogued meaning; `qualifiers` holds the others as `key=value` |
| `producer` | `APB2` or `apb-fasta` for fields APB writes; null for the vendor's own |
| `requirement` | `MUST`, `SHOULD` or `MAY` where the set sets requirements |
| `location`, `table`, `column` | Where the field lives; `column` is null when nothing supplies a required field |
| `inputs` | The vendor columns APB2 computes the column from |
| `needs` | What to run before the field exists, such as `apb-fasta verify-peptides` |
| `verdict` | The level's: `fail` when a MUST field is unsupported, `warn` when a SHOULD or MAY field is, `pass` otherwise; null for sets without requirements |

- Requirements live in `src/apb_catalog/data/requirements.json`, per set, level and kind, or in a plugin set's own `requirements.json`; no packaged set sets them
- APB2's fields count where the rule's level keeps their column; apb-fasta's count on every level, with `needs`
- A level with no catalogued or required field has one row without a kind
- The command line prints the same check: `apb-catalog check SET`, or `apb-catalog check SET spectronaut` for one vendor's fields; it exits 1 when a level fails
