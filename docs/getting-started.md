# Get started

Every example runs on a small synthetic DIA-NN 1.8.1 result, four runs by six precursors, and every output shown is what it returns: [tests/test_docs_examples.py](https://github.com/anndata-omics-bridge/apb-catalog/blob/main/tests/test_docs_examples.py) runs this page. Other vendors appear in the prose and tables only.

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
confidence = DataCatalog(diann, "confidence_alpha")
```

The second argument names the set; [Catalogues](catalogues.md) lists them all.

## See what it holds

```python
confidence.fields().select("level", "location", "name", "key", "qualifier.stage", "present")
```

```text
shape: (7, 6)
┌─────────────────┬──────────┬───────────────────┬─────────────────┬─────────────────┬─────────┐
│ level           ┆ location ┆ name              ┆ key             ┆ qualifier.stage ┆ present │
│ ---             ┆ ---      ┆ ---               ┆ ---             ┆ ---             ┆ ---     │
│ str             ┆ str      ┆ str               ┆ str             ┆ str             ┆ bool    │
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

`q_value` in `layers` is the q-value of each run; in `var`, the one across the whole experiment. Or ask one level which keys it offers in one slot:

```python
ion = confidence.levels["peptidoform_ion"]
ion.layers.keys()   # {'pep', 'q_value'}
ion.var.keys()      # {'library_q_value', 'q_value'}
```

Only the sets named answer.

## Get the data

| Call | Returns | One value per |
| --- | --- | --- |
| `layers.get(key)` | a numpy matrix, runs × features | run and feature |
| `var.get(key)` | the var column, a Polars `Series` | feature |
| `obs.get(key)` | the obs column, a Polars `Series` | run |
| `layers.name(key)`, `var.name(key)`, `obs.name(key)` | the field's name | |

```python
pep = ion.layers.get("pep")       # numpy, runs × precursors
pep.shape                         # (4, 6)
ion.layers.name("pep")            # 'PEP'
diann.levels["peptidoform_ion"].layers[ion.layers.name("pep")].wide().head(3)   # apb2's own table
```

```text
shape: (3, 4)
┌───────┬───────┬───────┬───────┐
│ obs_0 ┆ obs_1 ┆ obs_2 ┆ obs_3 │
│ ---   ┆ ---   ┆ ---   ┆ ---   │
│ f64   ┆ f64   ┆ f64   ┆ f64   │
╞═══════╪═══════╪═══════╪═══════╡
│ 0.01  ┆ 0.02  ┆ 0.03  ┆ 0.04  │
│ 0.02  ┆ 0.04  ┆ 0.06  ┆ null  │
│ 0.03  ┆ 0.06  ┆ null  ┆ 0.12  │
└───────┴───────┴───────┴───────┘
```

Spectronaut's PEP is `EG_PEP`, MaxQuant's `PEP`; `layers.name` names whichever the result holds.

The layer has the same runs and features, in the same order, as the level's abundance layer, so it can become weights directly:

```python
intensities = ion.X                # the primary layer, runs × precursors
weights = 1 - pep
weights.shape == intensities.shape  # True

ion.var.get("q_value").name        # 'Global_Q_Value'
```

`None` means the vendor reports no such field, or APB2 left it out because it held one value or none. Fall back explicitly:

```python
pep = ion.layers.get("pep")
if pep is None:
    q_value = ion.layers.get("q_value")
```

## Read a level as AnnData does

Name several sets. Only the sets named answer: `apb_alpha` holds the fields `apb2 convert` writes, such as `peptidoform_ion`, and answers only when named:

```python
catalog = DataCatalog(diann, "abundance_alpha", "confidence_alpha", "apb_alpha")
ion = catalog.levels["peptidoform_ion"]

ion.layers                         # key -> numpy matrix, runs by precursors
ion.var                            # key -> polars Series, one value per precursor
ion.layers["q_value"].shape        # (4, 6)
ion.var["peptidoform_ion"].name    # 'ProForma_ion'
ion.layers["Q_Value"]              # not a key: the level's own layer of that name
ion.layers.keys()                  # {'intensity', 'intensity_norm_settings', 'pep', 'q_value'}
ion.layers.name("q_value")         # 'Q_Value'
ion.layers.get("library_q_value")  # None
ion.var.get("library_q_value").name  # 'Lib_Q_Value'
```

A layer is a numpy matrix, runs by precursors, as AnnData's layers; a `var` column a polars Series. `name` gives the field a key reads. DIA-NN's library q-value is one value per precursor, so it is in `var`, not `layers`.

`get` returns `None` where `[...]` raises `KeyError`, and takes the qualifiers a key leaves open, as `ion.layers.get("retention_time", unit="minute")` with the `chromatography_alpha` set.

A name that is neither a key nor the level's own raises `KeyError`, as cf_xarray's `ds.cf[...]` does. A vendor may name a column as a key is named, so a prefix makes the lookup exact:

| Name | Answered by | Nothing answers |
| --- | --- | --- |
| `q_value` | a key of the composed sets, else the level's own field of that name | `get` gives `None`, `[...]` raises `KeyError` |
| `c:q_value` | the set whose prefix is `c`, confidence, alone; never a field of that name | the same |
| `v:Q_Value` | the level's own field of that name alone; never the catalog | the same |

`catalogues()` lists each set's prefix. Where a key names several columns, such as a prolfquapp table's `group` and `bait` columns with `obs_annotation_alpha` named on an annotated result, `obs["group"]` raises `UnresolvedField` and the list `obs[["group", "Run"]]` reads them all, then `Run`.

## Read the AnnData object with pandas

`apb_catalog.api_pandas` has the same `DataCatalog` for the AnnData or MuData object APB2 wrote: the same keys answer the same fields, with AnnData's own values.

```python
import mudata
from apb_catalog.api_pandas import DataCatalog

mdata = mudata.read_h5mu("diann.h5mu")
ion = DataCatalog(mdata, "abundance_alpha", "confidence_alpha", "apb_alpha").levels["peptidoform_ion"]

ion.layers                                # key -> the matrix AnnData holds, runs by precursors
ion.var                                   # key -> pandas Series, one value per precursor
ion.layers["q_value"] is mdata["peptidoform_ion"].layers["Q_Value"]   # True
ion.var[["q_value", "peptidoform_ion"]]   # a pandas DataFrame
```

An `.h5ad` read with `anndata.read_h5ad` is the one level it holds. `UnresolvedField` comes from `apb_catalog.api`.

`as_mudata()` converts: a new MuData of the catalogued fields alone, each under its key, which `write_h5mu` writes. See [A result named by catalog keys](keyed.md).

## Keys stand for a kind and its qualifiers

Each set lists its keys; a key names one meaning, a kind with the qualifier values it fixes. In the `abundance_alpha` set the key says whether the software normalizes the value across runs, as PSI-MS names raw and normalized values apart.

| Call | Key stands for | Returns |
| --- | --- | --- |
| `layers.get("intensity")` | `intensity`, normalization `none` | DIA-NN `Precursor_Quantity`, MaxQuant `Intensity` |
| `layers.get("intensity_norm_settings")` | `intensity`, normalization `run_setting` | DIA-NN `Precursor_Normalised`: whatever normalization the run chose, possibly none |
| `layers.get("intensity_norm_unknown")` | `intensity`, normalization `unknown` | FragPipe, Sage `Intensity`: nobody documented whether it is normalized |
| `var.get("quantification_q_value")` | `q_value`, stage `quantification` | Sage `Q_Value`, the q-value of its MS1 peak |

- Asking `intensity` where the normalization is unknown raises `UnresolvedField`: the layer may or may not be normalized
- A level has at most one field per key and location. Where a tool reports several, such as AlphaPept's four MS1 sums, the catalog names one and the others stay readable by name through the result
- `fields()` has `key` and `kind` columns and a `qualifier.<name>` column per other qualifier, so "everything normalized" is one filter on `qualifier.normalization`

## Narrow with qualifiers

A qualifier the key leaves open is a keyword of `get` and `name`; [Catalogues](catalogues.md) lists each set's keys and values.

| Set | Call on the `peptidoform_ion` level | Returns |
| --- | --- | --- |
| `chromatography_alpha` | `layers.get("retention_time", unit="minute")` | DIA-NN `RT` |
| `chromatography_alpha` | `layers.get("retention_time", unit="second")` | DIA-NN `None`: its RT is in minutes |
| `chromatography_alpha` | `layers.get("aligned_retention_time")` | MaxQuant `Calibrated_retention_time` |

- A keyword the key already fixes, such as `stage` with `q_value`, raises `ValueError`
- `[...]` takes no keywords

## Names without data

`Catalog` takes a software name and version instead of a result; its levels have the same slots, holding names:

```python
from apb_catalog.api import Catalog

ion = Catalog("DIA-NN", "2.6.0", "abundance_alpha").levels["peptidoform_ion"]
ion.layers["intensity"]            # 'Precursor_Quantity'
apb = Catalog("DIA-NN", "2.6.0", "apb_alpha").levels["peptidoform_ion"]
apb.var[["peptidoform_ion", "protein_assignment"]]  # ('ProForma_ion', 'Protein_Group')
```

`get` returns the name or `None` and takes qualifiers too: `Catalog("DIA-NN", "2.6.0", "chromatography_alpha").levels["peptidoform_ion"].layers.get("retention_time", unit="minute")` is `'RT'`.

## When there is no single answer

| Call | Raises |
| --- | --- |
| DIA-NN 1.8 `abundance.levels["protein"].layers.get("intensity_norm_settings")` | `UnresolvedField`, ambiguous: `PG_Normalised` and `PG_MaxLFQ` both are; `aggregation="maxlfq"` picks one |
| Spectronaut `abundance.levels["protein"].layers.get("intensity_norm_settings", aggregation="sum")` | `UnresolvedField`, unknown: `PG_Quantity` leaves aggregation unknown |
| `layers.get("intensity", normalization="none")` | `ValueError`: the key `intensity` fixes normalization |
| `layers["intensities"]` | `KeyError`: no key or field `intensities`; `get` returns `None`, as `dict.get` |
| `Catalog("DIA-NN", "3.0", "confidence_alpha")` | `ValueError`: no packaged DIA-NN rule admits version `3.0` |

```python
from apb_catalog.api import DataCatalog, UnresolvedField

abundance = DataCatalog(diann, "abundance_alpha")
try:
    layer = abundance.levels["protein"].layers.get("intensity_norm_settings")
except UnresolvedField as error:
    print(error)   # names the reason and the candidate fields
```

```text
intensity_norm_settings (kind=intensity, normalization=run_setting) on protein is ambiguous: 2 entries match: PG_Normalised, PG_MaxLFQ; candidates: PG_Normalised, PG_MaxLFQ
```

## Record what was looked up

```python
from apb2.api import write_parsed_levels
from apb_catalog.api import ResolutionSnapshot, attach_snapshot

confidence.levels["peptidoform_ion"].layers.get("q_value")
annotated = attach_snapshot(diann, confidence.snapshot())
write_parsed_levels(annotated, Path("annotated.h5mu"))

record = read_parsed_levels(Path("annotated.h5mu")).metadata["catalog"]["confidence_alpha"]["result"]
stored = ResolutionSnapshot.model_validate(record)
[(r.request.level, r.status, r.reference.name) for r in stored.resolutions]
```

```text
[('peptidoform_ion', 'resolved', 'PEP'), ('peptidoform_ion', 'resolved', 'Global_Q_Value'), ('peptidoform_ion', 'resolved', 'Q_Value')]
```

The snapshot holds every lookup `confidence` answered on this page, in order.

The snapshot is plain JSON in the result, readable without APB Catalog; [Python API](api.md#snapshots) says where.
