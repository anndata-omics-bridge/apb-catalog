# Get started

## Install

APB Catalog requires Python 3.13 and APB2. A new APB2 rule version needs its own catalogue variant (see [Maintaining](maintaining.md)). Clone both repositories as siblings:

```bash
mkdir anndata_bridge
cd anndata_bridge
git clone https://github.com/anndata-omics-bridge/apb2.git
git clone https://github.com/anndata-omics-bridge/apb-catalog.git
cd apb-catalog
uv sync
```

```text
anndata_bridge/
├── apb2/
└── apb-catalog/
```

## Read a converted result

Any APB2 result works: h5ad, h5mu, Parquet or DuckDB. The outputs below come from a DIA-NN 2.6.0 ProteoBench submission converted by APB2, with an ion and a protein level.

```python
from pathlib import Path

from apb2.api import read_parsed_levels
from apb_catalog.api import Catalog

parsed = read_parsed_levels(Path("converted.h5mu"))
confidence = Catalog(parsed, "identification_confidence")
```

## See what the result holds

```python
confidence.fields().select("level", "location", "name", "kind", "stage")
```

```text
┌─────────┬──────────┬───────────────────┬─────────────────┬────────────────┐
│ level   ┆ location ┆ name              ┆ kind            ┆ stage          │
╞═════════╪══════════╪═══════════════════╪═════════════════╪════════════════╡
│ ion     ┆ layers   ┆ Q_Value           ┆ q_value         ┆ identification │
│ ion     ┆ layers   ┆ PEP               ┆ pep             ┆ identification │
│ ion     ┆ var      ┆ Global_Q_Value    ┆ global_q_value  ┆ identification │
│ protein ┆ layers   ┆ PG_Q_Value        ┆ q_value         ┆ identification │
│ protein ┆ var      ┆ Lib_PG_Q_Value    ┆ library_q_value ┆ identification │
│ protein ┆ var      ┆ Global_PG_Q_Value ┆ global_q_value  ┆ identification │
└─────────┴──────────┴───────────────────┴─────────────────┴────────────────┘
```

Or ask one level which kinds it offers, per run (`layer`) or per feature (`var`):

```python
confidence.layer("ion")   # ('pep', 'q_value')
confidence.var("ion")     # ('global_q_value',)
```

## Get the data

```python
pep = confidence.layer("ion", kind="pep")
pep.layer_name      # 'PEP'; Spectronaut gives 'EG_PEP', MaxQuant 'PEP'
pep.wide().head(3)
```

```text
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ obs_0    ┆ obs_1    ┆ obs_2    ┆ obs_3    ┆ obs_4    ┆ obs_5    │
╞══════════╪══════════╪══════════╪══════════╪══════════╪══════════╡
│ 0.000224 ┆ 0.000061 ┆ 0.000173 ┆ 0.000223 ┆ 0.000128 ┆ 0.000038 │
│ 0.000002 ┆ 0.000002 ┆ 0.000062 ┆ 0.000041 ┆ 0.000064 ┆ NaN      │
│ 0.000224 ┆ 0.000061 ┆ 0.000173 ┆ 0.001122 ┆ 0.000445 ┆ 0.000207 │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

`wide()` returns one column per run; its rows are the level's features in their order, `ion.var.frame`. The layer has the same ions and runs, in the same order, as the abundance layer, so it can become weights directly:

```python
ion = parsed.levels["ion"]
abundance = ion.layers[ion.primary_layer_name]
intensities = abundance.wide().to_numpy()   # (18182, 6)
weights = 1 - pep.wide().to_numpy()         # (18182, 6), NaN where absent
```

A per-feature field is a column of the feature table, one value per ion:

```python
global_q = confidence.var("ion", kind="global_q_value")
global_q.name       # 'Global_Q_Value'
global_q.len()      # 18182
```

When the vendor reports no such field, or APB2 left it out of this result because it held one value or none (the level's parse record lists it under `result.uninformative_fields`), the lookup returns `None`; DIA-NN 1.7, for example, has no `PEP`. Fall back explicitly:

```python
pep = confidence.layer("ion", kind="pep")
if pep is None:
    q_value = confidence.layer("ion", kind="q_value")
```

## When there is no single answer

```python
from apb_catalog.api import UnresolvedField

try:
    pep = confidence.layer("ion", kind="pep")
except UnresolvedField as error:
    print(error)    # names the reason and any candidate fields
```

It is raised when no catalogue variant names the level's software version, typically a new APB2 rule version, or when a level was produced by another tool. Add the variant as described in [Maintaining](maintaining.md).

## Record what was looked up

```python
from apb2.api import write_parsed_levels
from apb_catalog.api import attach_snapshot, stored_snapshot

write_parsed_levels(attach_snapshot(parsed, confidence.snapshot()), Path("annotated.h5mu"))
stored_snapshot(read_parsed_levels(Path("annotated.h5mu")), "identification_confidence").resolutions
# two resolved lookups: layer 'PEP' and var column 'Global_Q_Value'
```

The snapshot sits at `metadata["catalog"]["identification_confidence"]["result"]` and can be read as plain JSON without APB Catalog installed.
