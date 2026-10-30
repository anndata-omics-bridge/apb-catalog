# Get started

Every output below is what the call returned on 26 October 2026, on APB2 results of four ProteoBench submissions: DIA-NN 2.6.0, MaxQuant 2.8.1.0, Spectronaut 20 and Sage 0.15.

## Install

```bash
pip install apb-catalog
```

## Open a result

```python
from pathlib import Path

from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

diann = read_parsed_levels(Path("diann.h5mu"))   # any APB2 result: h5ad, h5mu, Parquet, DuckDB
confidence = DataCatalog(diann, "confidence")
```

The second argument names the set; [Catalogues](catalogues.md) lists them all.

## See what it holds

```python
confidence.fields().select("level", "location", "name", "qualifier.kind", "qualifier.stage", "present")
```

```text
┌─────────────────┬──────────┬───────────────────┬─────────────────┬─────────────────┬─────────┐
│ level           ┆ location ┆ name              ┆ qualifier.kind  ┆ qualifier.stage ┆ present │
╞═════════════════╪══════════╪═══════════════════╪═════════════════╪═════════════════╪═════════╡
│ peptidoform_ion ┆ layers   ┆ Q_Value           ┆ q_value         ┆ identification  ┆ true    │
│ peptidoform_ion ┆ layers   ┆ PEP               ┆ pep             ┆ identification  ┆ true    │
│ peptidoform_ion ┆ var      ┆ Global_Q_Value    ┆ global_q_value  ┆ identification  ┆ true    │
│ peptidoform_ion ┆ var      ┆ Lib_Q_Value       ┆ library_q_value ┆ identification  ┆ true    │
│ protein         ┆ layers   ┆ PG_Q_Value        ┆ q_value         ┆ identification  ┆ true    │
│ protein         ┆ var      ┆ Lib_PG_Q_Value    ┆ library_q_value ┆ identification  ┆ true    │
│ protein         ┆ var      ┆ Global_PG_Q_Value ┆ global_q_value  ┆ identification  ┆ true    │
└─────────────────┴──────────┴───────────────────┴─────────────────┴─────────────────┴─────────┘
```

Or ask one level which kinds it offers at one location:

```python
confidence.kinds("peptidoform_ion", "layers")   # ('pep', 'q_value')
confidence.kinds("peptidoform_ion", "var")      # ('global_q_value', 'library_q_value')
```

## Get the data

| Call | Returns | One value per |
| --- | --- | --- |
| `layer(level, kind=...)` | the apb2 layer table | run and feature |
| `var(level, kind=...)` | the var column, a Polars `Series` | feature |
| `obs(level, kind=...)` | the obs column, a Polars `Series` | run |

```python
pep = confidence.layer("peptidoform_ion", kind="pep")
pep.layer_name        # 'PEP'; Spectronaut's is 'EG_PEP', MaxQuant's 'PEP'
pep.wide().head(3)
```

```text
┌──────────┬──────────┬──────────┬──────────┬──────────┬──────────┐
│ obs_0    ┆ obs_1    ┆ obs_2    ┆ obs_3    ┆ obs_4    ┆ obs_5    │
╞══════════╪══════════╪══════════╪══════════╪══════════╪══════════╡
│ 0.000224 ┆ 0.000061 ┆ 0.000173 ┆ 0.000223 ┆ 0.000128 ┆ 0.000038 │
│ 0.000002 ┆ 0.000002 ┆ 0.000062 ┆ 0.000041 ┆ 0.000064 ┆ null     │
│ 0.000224 ┆ 0.000061 ┆ 0.000173 ┆ 0.001122 ┆ 0.000445 ┆ 0.000207 │
└──────────┴──────────┴──────────┴──────────┴──────────┴──────────┘
```

The layer has the same features and runs, in the same order, as the level's abundance layer, so it can become weights directly:

```python
ion = diann.levels["peptidoform_ion"]
intensities = ion.layers[ion.primary_layer_name].wide().to_numpy()   # (18182, 6)
weights = 1 - pep.wide().to_numpy()                                  # (18182, 6)

confidence.var("peptidoform_ion", kind="global_q_value").name        # 'Global_Q_Value', 18182 values
```

`None` means the vendor reports no such field, or APB2 left it out because it held one value or none. Fall back explicitly:

```python
pep = confidence.layer("peptidoform_ion", kind="pep")
if pep is None:
    q_value = confidence.layer("peptidoform_ion", kind="q_value")
```

## Narrow with qualifiers

Every qualifier besides `kind` is a keyword; [Catalogues](catalogues.md) lists each set's values.

| Set | Call | Returns |
| --- | --- | --- |
| `abundance` | `layer("peptidoform_ion", kind="intensity", normalization="none")` | DIA-NN `Precursor_Quantity`, MaxQuant `Intensity` |
| `abundance` | `layer("peptidoform_ion", kind="intensity", normalization="run_setting")` | DIA-NN `Precursor_Normalised` |
| `confidence` | `var("peptidoform_ion", kind="q_value", stage="quantification")` | Sage `Q_Value`, the q-value of its MS1 peak |
| `chromatography` | `layer("peptidoform_ion", kind="retention_time", unit="minute")` | DIA-NN `RT` |
| `chromatography` | `layer("peptidoform_ion", kind="retention_time", unit="second")` | DIA-NN `None`: its RT is in minutes |
| `chromatography` | `layer("peptidoform_ion", kind="aligned_retention_time")` | MaxQuant `Calibrated_Retention_Time` |

- Confidence lookups mean the identification unless `stage="quantification"` says otherwise
- `kinds` takes the same keywords: `kinds("peptidoform_ion", "var", stage="quantification")` is `('q_value',)` for Sage

## Names without data

`Catalog` takes a software name and version instead of a result, and returns a `Reference`:

```python
from apb_catalog.api import Catalog

Catalog("DIA-NN", "2.6.0", "abundance").layer("peptidoform_ion", kind="intensity", normalization="none").name
# 'Precursor_Quantity'
Catalog("DIA-NN", "2.6.0", "apb").var("peptidoform_ion", kind="protein_assignment").name
# 'Protein_Group'
```

## When there is no single answer

| Call | Raises |
| --- | --- |
| DIA-NN `abundance.layer("peptidoform_ion", kind="intensity")` | `UnresolvedField`, ambiguous: `Precursor_Quantity`, `Precursor_Normalised` both match |
| Spectronaut `abundance.layer("peptidoform_ion", kind="intensity", normalization="none")` | `UnresolvedField`, unknown: `EG_TotalQuantity_Settings`, `EG_TargetQuantity_Settings` and `EG_ReferenceQuantity_Settings` leave normalization unknown |
| Spectronaut `abundance.layer("protein", kind="intensity")` | `UnresolvedField`, unknown: `PG_Quantity` leaves kind unknown |
| `layer("peptidoform_ion", kind="intensity", normalisation="none")` | `ValueError`: unknown qualifier `normalisation` |
| `layer("peptidoform_ion", kind="intensities")` | `ValueError`: `kind` does not admit `intensities`, with the admitted kinds |
| `Catalog("DIA-NN", "3.0", "confidence")` | `ValueError`: no packaged DIA-NN rule admits version `3.0` |

```python
from apb_catalog.api import UnresolvedField

abundance = DataCatalog(diann, "abundance")
try:
    layer = abundance.layer("peptidoform_ion", kind="intensity")
except UnresolvedField as error:
    print(error)   # names the reason and the candidate fields
```

## Record what was looked up

```python
from apb2.api import write_parsed_levels
from apb_catalog.api import attach_snapshot, stale_levels, stored_snapshot

confidence.layer("peptidoform_ion", kind="q_value")
annotated = attach_snapshot(diann, confidence.snapshot())
write_parsed_levels(annotated, Path("annotated.h5mu"))

stored = stored_snapshot(read_parsed_levels(Path("annotated.h5mu")), "confidence")
[(r.request.level, r.status, r.reference.name) for r in stored.resolutions]
# [('peptidoform_ion', 'resolved', 'Q_Value')]

stale_levels(annotated, confidence.snapshot())   # (): software name and version unchanged
```

The snapshot is plain JSON in the result, readable without APB Catalog; [Python API](api.md#snapshots) says where.
