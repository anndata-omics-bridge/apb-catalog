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
confidence.fields().select("level", "location", "name", "key", "qualifier.stage", "present")
```

```text
┌─────────────────┬──────────┬───────────────────┬─────────────────┬─────────────────┬─────────┐
│ level           ┆ location ┆ name              ┆ key             ┆ qualifier.stage ┆ present │
╞═════════════════╪══════════╪═══════════════════╪═════════════════╪═════════════════╪═════════╡
│ peptidoform_ion ┆ layers   ┆ Q_Value           ┆ q_value         ┆ identification  ┆ true    │
│ peptidoform_ion ┆ layers   ┆ PEP               ┆ pep             ┆ identification  ┆ true    │
│ peptidoform_ion ┆ var      ┆ Global_Q_Value    ┆ q_value         ┆ identification  ┆ true    │
│ peptidoform_ion ┆ var      ┆ Lib_Q_Value       ┆ library_q_value ┆ identification  ┆ true    │
│ protein         ┆ layers   ┆ PG_Q_Value        ┆ q_value         ┆ identification  ┆ true    │
│ protein         ┆ var      ┆ Lib_PG_Q_Value    ┆ library_q_value ┆ identification  ┆ true    │
│ protein         ┆ var      ┆ Global_PG_Q_Value ┆ q_value         ┆ identification  ┆ true    │
└─────────────────┴──────────┴───────────────────┴─────────────────┴─────────────────┴─────────┘
```

`q_value` in `layers` is the q-value of each run; in `var`, the one across the whole experiment. Or ask one level which keys it offers at one location:

```python
confidence.keys("peptidoform_ion", "layers")   # ('pep', 'q_value')
confidence.keys("peptidoform_ion", "var")      # ('library_q_value', 'q_value')
```

## Get the data

| Call | Returns | One value per |
| --- | --- | --- |
| `layer(level, key)` | the apb2 layer table | run and feature |
| `var(level, key)` | the var column, a Polars `Series` | feature |
| `obs(level, key)` | the obs column, a Polars `Series` | run |

```python
pep = confidence.layer("peptidoform_ion", "pep")
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

confidence.var("peptidoform_ion", "q_value").name                    # 'Global_Q_Value', 18182 values
```

`None` means the vendor reports no such field, or APB2 left it out because it held one value or none. Fall back explicitly:

```python
pep = confidence.layer("peptidoform_ion", "pep")
if pep is None:
    q_value = confidence.layer("peptidoform_ion", "q_value")
```

## Read a level as AnnData does

Name several sets; `apb`, APB's own fields, is always in:

```python
catalog = DataCatalog(diann, "abundance", "confidence")
ion = catalog.levels["peptidoform_ion"]

ion.layers["q_value"].shape        # (6, 18182): runs by precursors, numpy, as AnnData's layers
ion.var["peptidoform_ion"].name    # 'ProForma_ion', a polars Series
ion.layers["Q_Value"]              # not a key: the level's own layer of that name
ion.layers.keys()                  # the keys it offers: {'intensity', 'normalized_intensity', 'q_value', ...}
```

A name that is neither a key nor the level's own raises `KeyError`, as cf_xarray's `ds.cf[...]` does.

## Keys stand for a kind and its qualifiers

Each set lists its keys; a key names one meaning, a kind with the qualifier values it fixes. In the `abundance` set the key says whether the software normalizes the value across runs, as PSI-MS names raw and normalized values apart.

| Call | Key stands for | Returns |
| --- | --- | --- |
| `layer("peptidoform_ion", "intensity")` | `intensity`, normalization `none` | DIA-NN `Precursor_Quantity`, MaxQuant `Intensity` |
| `layer("peptidoform_ion", "normalized_intensity")` | `intensity`, normalization `run_setting` | DIA-NN `Precursor_Normalised`: whatever normalization the run chose, possibly none |
| `layer("peptidoform_ion", "intensity_unknown_normalization")` | `intensity`, normalization `unknown` | FragPipe, Sage `Intensity`: nobody documented whether it is normalized |
| `var("peptidoform_ion", "quantification_q_value")` | `q_value`, stage `quantification` | Sage `Q_Value`, the q-value of its MS1 peak |

- Asking `intensity` where the normalization is unknown raises `UnresolvedField`: the layer may or may not be normalized
- A level has at most one field per key and location. Where a tool reports several, such as AlphaPept's four MS1 sums, the catalog names one and the others stay readable by name through the result
- `fields()` has `key` and `kind` columns and a `qualifier.<name>` column per other qualifier, so "everything normalized" is one filter on `qualifier.normalization`

## Narrow with qualifiers

A qualifier the key leaves open is a keyword; [Catalogues](catalogues.md) lists each set's keys and values.

| Set | Call | Returns |
| --- | --- | --- |
| `chromatography` | `layer("peptidoform_ion", "retention_time", unit="minute")` | DIA-NN `RT` |
| `chromatography` | `layer("peptidoform_ion", "retention_time", unit="second")` | DIA-NN `None`: its RT is in minutes |
| `chromatography` | `layer("peptidoform_ion", "aligned_retention_time")` | MaxQuant `Calibrated_Retention_Time` |

- A keyword the key already fixes, such as `stage` with `q_value`, raises `ValueError`
- `keys` takes the same keywords: `keys("peptidoform_ion", "layers", unit="minute")`

## Names without data

`Catalog` takes a software name and version instead of a result, and returns a `Reference`:

```python
from apb_catalog.api import Catalog

Catalog("DIA-NN", "2.6.0", "abundance").layer("peptidoform_ion", "intensity").name
# 'Precursor_Quantity'
Catalog("DIA-NN", "2.6.0", "apb").var("peptidoform_ion", "protein_assignment").name
# 'Protein_Group'
```

## When there is no single answer

| Call | Raises |
| --- | --- |
| Spectronaut `abundance.layer("protein", "normalized_intensity")` | `UnresolvedField`, unknown: `PG_Quantity` leaves kind unknown |
| `abundance.layer("peptidoform_ion", "intensity", normalization="none")` | `ValueError`: the key `intensity` fixes normalization |
| `layer("peptidoform_ion", "intensities")` | `ValueError`: unknown key `intensities`, with the set's keys |
| `Catalog("DIA-NN", "3.0", "confidence")` | `ValueError`: no packaged DIA-NN rule admits version `3.0` |

```python
from apb_catalog.api import UnresolvedField

abundance = DataCatalog(spectronaut, "abundance")
try:
    layer = abundance.layer("protein", "normalized_intensity")
except UnresolvedField as error:
    print(error)   # names the reason and the candidate fields
```

## Record what was looked up

```python
from apb2.api import write_parsed_levels
from apb_catalog.api import attach_snapshot, stale_levels, stored_snapshot

confidence.layer("peptidoform_ion", "q_value")
annotated = attach_snapshot(diann, confidence.snapshot())
write_parsed_levels(annotated, Path("annotated.h5mu"))

stored = stored_snapshot(read_parsed_levels(Path("annotated.h5mu")), "confidence")
[(r.request.level, r.status, r.reference.name) for r in stored.resolutions]
# [('peptidoform_ion', 'resolved', 'Q_Value')]

stale_levels(annotated, confidence.snapshot())   # (): software name and version unchanged
```

The snapshot is plain JSON in the result, readable without APB Catalog; [Python API](api.md#snapshots) says where.
