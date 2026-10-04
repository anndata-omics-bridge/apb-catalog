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
- Misspelled concepts, kinds or catalogue names raise `ValueError`

## When there is no single answer

`UnresolvedField` (from `apb_catalog.api`) is raised, naming the reason and the candidates, when:

- two catalogued fields fit equally well, or
- the level's rule was never reviewed, for example a result converted before an APB2 rule change, or a level produced by another tool

`None` always means the rule was reviewed and the field is not there.

## Snapshots

```python
from apb_catalog.api import attach_snapshot, stale_levels, stored_snapshot

annotated = attach_snapshot(parsed, catalog.snapshot())   # new result; data shared, not copied
stored_snapshot(annotated, "identification_confidence")                   # read it back
stale_levels(annotated, catalog.snapshot())               # levels whose rule changed since
```

The snapshot is stored as JSON at `metadata["catalog"][<set>]`, beside other sets' snapshots, and persists in h5ad, h5mu, Parquet and DuckDB. It embeds the set's description, concept definitions, level bindings, catalogued fields and every answer, so a reader needs neither this package nor its catalogues. Its JSON Schema ships as `apb_catalog/data/apb-catalog-resolution-0.2.schema.json`.
