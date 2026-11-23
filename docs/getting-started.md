# Get started

Every example runs on a small synthetic DIA-NN 1.8.1 result, four runs by six precursors, and every output shown is what it returns: [tests/test_docs_examples.py](https://github.com/anndata-omics-bridge/apb-catalog/blob/main/tests/test_docs_examples.py) runs this page. Other vendors appear in the prose and tables only.

## Install

```bash
pip install apb-catalog
```

The default install supports name lookups and HDF5 results (`.h5ad` and `.h5mu`). APB2 can pass DuckDB and Parquet results to `DataCatalog` through `read_parsed_levels`. Install `apb2[duckdb]` to use DuckDB. Install `apb2[excel]` when converting MSAngel or ProlineStudio workbooks with APB2.

## Get the data

Open an APB2 result, name the sets to ask, and read each level by key, as AnnData reads it by name. `apb_catalog.api` answers with numpy matrices and Polars Series:

```python
from pathlib import Path

from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

diann = read_parsed_levels(Path("diann.h5mu"))   # any APB2 result: h5ad, h5mu, Parquet, DuckDB
catalog = DataCatalog(diann, "abundance_alpha", "confidence_alpha", "apb_alpha")
ion = catalog.levels["peptidoform_ion"]

ion.X.shape                          # (4, 6)
ion.layers                           # key -> numpy matrix, runs × precursors
ion.var                              # key -> Polars Series, one value per precursor
ion.var["peptidoform_ion"].name      # 'ProForma_ion'
ion.layers.name("pep")               # 'PEP'
ion.layers.name("q_value")           # 'Q_Value'
ion.var.get("q_value").name          # 'Global_Q_Value'
ion.layers.get("library_q_value")    # None
pep = ion.layers["pep"]              # numpy, runs × precursors
pep
```

```text
array([[0.01, 0.02, 0.03, 0.04, 0.06,  nan],
       [0.02, 0.04, 0.06,  nan, 0.12, 0.1 ],
       [0.03, 0.06,  nan, 0.12, 0.18, 0.15],
       [0.04,  nan, 0.12, 0.16, 0.24, 0.2 ]])
```

The arguments after the result name the sets; only the sets named answer, and [Sets](sets.md) lists them all. `apb_alpha` holds the fields `apb2 convert` writes for every vendor, such as the ProForma identifier `peptidoform_ion`. Spectronaut's PEP is `EG_PEP`, MaxQuant's `PEP`; `pep` reads whichever the result holds. `q_value` in `layers` is the q-value of each run; in `var`, the one across the whole experiment.

| Call | Returns | One value per |
| --- | --- | --- |
| `X` | the level's primary layer, a numpy matrix, runs × features | run and feature |
| `layers[key]` | a numpy matrix, runs × features, as `adata.layers[key]`; `KeyError` when absent | run and feature |
| `var[key]`, `obs[key]` | the var or obs column, a Polars `Series`; `KeyError` when absent | feature, run |
| `layers.get(key)`, `var.get(key)`, `obs.get(key)` | the same, or `None` when absent | |
| `var[[key, ...]]` | several columns, a Polars `DataFrame` | feature |
| `layers.name(key)`, `var.name(key)`, `obs.name(key)` | the field's name | |

`get` and `name` take the qualifiers a key leaves open, as `ion.layers.get("retention_time", unit="minute")` with the `chromatography_alpha` set; `[...]` takes none.

DIA-NN's library q-value is one value per precursor, so it is in `var`, not `layers`. Every layer has the runs and features of `X`, in the same order, so it can become weights directly:

```python
weights = 1 - pep
weights.shape == ion.X.shape        # True
ion.var.get("library_q_value").name  # 'Lib_Q_Value'
```

`None` means the vendor reports no such field, or APB2 left it out because it held one value or none. Fall back explicitly:

```python
pep = ion.layers.get("pep")
if pep is None:
    q_value = ion.layers.get("q_value")
```

## Get the data with pandas

`apb_catalog.api_pandas` has the same `DataCatalog` for the AnnData or MuData object APB2 wrote: the same keys answer the same fields, with AnnData's own matrices and pandas Series.

```python
import mudata
from apb_catalog.api_pandas import DataCatalog

mdata = mudata.read_h5mu("diann.h5mu")
ion = DataCatalog(mdata, "abundance_alpha", "confidence_alpha", "apb_alpha").levels["peptidoform_ion"]

ion.layers                                # key -> the matrix AnnData holds, runs × precursors
ion.var                                   # key -> pandas Series, one value per precursor
ion.layers["pep"] is mdata["peptidoform_ion"].layers["PEP"]           # True
ion.layers["q_value"] is mdata["peptidoform_ion"].layers["Q_Value"]   # True
ion.var[["peptidoform_ion", "protein_assignment"]]
```

```text
                              ProForma_ion   Protein_Group
pfi:PEPTIDEK/2                  PEPTIDEK/2              P1
pfi:AAC[UNIMOD:4]LLK/2  AAC[UNIMOD:4]LLK/2  sp|P2|P2_HUMAN
pfi:YEASTPEPK/2                YEASTPEPK/2              P3
pfi:CONTPEPK/2                  CONTPEPK/2         Cont_P4
pfi:LASTPEPK/2                  LASTPEPK/2              P7
pfi:SHAREDK/2                    SHAREDK/2      P5;CON__P6
```

An `.h5ad` read with `anndata.read_h5ad` is the one level it holds. `UnresolvedField` comes from `apb_catalog.api`. `as_mudata()` converts: a new MuData of the cataloged fields alone, each under its key; see [A result named by catalog keys](keyed.md).

## Prefixes: one set, or the level's own name

A name that is not a key reads the level's own field of that name, as AnnData does:

```python
ion.layers["Q_Value"].shape        # (4, 6)
```

A name that is neither a key nor the level's own raises `KeyError`, as cf_xarray's `ds.cf[...]` does. A vendor may name a column as a key is named, so a prefix makes the lookup exact:

| Name | Answered by | Nothing answers |
| --- | --- | --- |
| `q_value` | a key of the composed sets, else the level's own field of that name | `get` gives `None`, `[...]` raises `KeyError` |
| `c:q_value` | the set whose prefix is `c`, confidence, alone; never a field of that name | the same |
| `v:Q_Value` | the level's own field of that name alone; never the catalog | the same |

Each set has its own prefix; `v` is reserved for the level's own names:

| Prefix | Set | Example | Asks for |
| --- | --- | --- | --- |
| `a` | [`abundance_alpha`](sets.md#abundance_alpha) | `a:intensity` | the level's measured intensity |
| `c` | [`confidence_alpha`](sets.md#confidence_alpha) | `c:q_value` | the q-value the software reports for the identification |
| `pbe` | [`proteobench_entrapment_alpha`](sets.md#proteobench_entrapment_alpha) | `pbe:q_value` | the precursor q-value ProteoBench's entrapment scoring ranks by |
| `rt` | [`chromatography_alpha`](sets.md#chromatography_alpha) | `rt:retention_time` | the feature's retention time |
| `apb` | [`apb_alpha`](sets.md#apb_alpha) | `apb:peptidoform_ion` | the ProForma ion identifier APB2 writes for every vendor |
| `annot` | [`obs_annotation_alpha`](sets.md#obs_annotation_alpha) | `annot:group` | each run's group, once `apb2 annotate` has run |
| `fpep` | [`fasta_peptides_alpha`](sets.md#fasta_peptides_alpha) | `fpep:reported_leading_gene_name` | the gene name of the peptide's leading protein in the FASTA, once `apb-fasta verify-peptides` has run |
| `fprot` | [`fasta_proteins_alpha`](sets.md#fasta_proteins_alpha) | `fprot:fasta_gene_names` | the protein's gene names from the FASTA, once `apb-fasta merge-annotations` has run |
| `v` | none | `v:Q_Value` | the level's own field `Q_Value`, never the catalog |

`confidence_alpha` and `proteobench_entrapment_alpha` both have a `q_value` key, so with both named, `c:` and `pbe:` say which set answers. On the level opened above, with `abundance_alpha`, `confidence_alpha` and `apb_alpha`:

```python
ion.layers.name("a:intensity")       # 'Precursor_Quantity'
ion.layers.name("c:q_value")         # 'Q_Value'
ion.var.name("apb:peptidoform_ion")  # 'ProForma_ion'
ion.layers.name("v:Q_Value")         # 'Q_Value'
```

A prefix answers only when its set is named: on `DataCatalog(diann, "confidence_alpha")`, `a:intensity` raises `ValueError`, and the message lists the prefixes that do answer, here `c` and `v`.

`sets()` lists each set's prefix. Where a key names several columns, such as a prolfquapp table's `group` and `bait` columns with `obs_annotation_alpha` named on an annotated result, `obs["group"]` raises `UnresolvedField` and the list `obs[["group", "Run"]]` reads them all, then `Run`.

## See what a result holds

```python
from apb_catalog.api import DataCatalog

confidence = DataCatalog(diann, "confidence_alpha")
confidence.fields().select("level", "slot", "name", "key", "qualifier.stage", "present")
```

```text
shape: (7, 6)
┌─────────────────┬────────┬───────────────────┬─────────────────┬─────────────────┬─────────┐
│ level           ┆ slot   ┆ name              ┆ key             ┆ qualifier.stage ┆ present │
│ ---             ┆ ---    ┆ ---               ┆ ---             ┆ ---             ┆ ---     │
│ str             ┆ str    ┆ str               ┆ str             ┆ str             ┆ bool    │
╞═════════════════╪════════╪═══════════════════╪═════════════════╪═════════════════╪═════════╡
│ peptidoform_ion ┆ layers ┆ Q_Value           ┆ q_value         ┆ identification  ┆ true    │
│ peptidoform_ion ┆ layers ┆ PEP               ┆ pep             ┆ identification  ┆ true    │
│ peptidoform_ion ┆ var    ┆ Global_Q_Value    ┆ q_value         ┆ identification  ┆ true    │
│ peptidoform_ion ┆ var    ┆ Lib_Q_Value       ┆ library_q_value ┆ identification  ┆ true    │
│ protein         ┆ layers ┆ PG_Q_Value        ┆ q_value         ┆ identification  ┆ true    │
│ protein         ┆ var    ┆ Lib_PG_Q_Value    ┆ library_q_value ┆ identification  ┆ true    │
│ protein         ┆ var    ┆ Global_PG_Q_Value ┆ q_value         ┆ identification  ┆ true    │
└─────────────────┴────────┴───────────────────┴─────────────────┴─────────────────┴─────────┘
```

`q_value` in `layers` is the q-value of each run; in `var`, the one across the whole experiment. Or ask one level which keys it offers in one slot:

```python
ion = confidence.levels["peptidoform_ion"]
ion.layers.keys()   # {'pep', 'q_value'}
ion.var.keys()      # {'library_q_value', 'q_value'}
```

Only the sets named answer.

## Require what an application needs

A set's requirement rows say how strongly an application needs a field on each level: `required`, `recommended` or `optional`. `abundance_alpha` recommends an intensity on the precursor level; `apb_alpha` requires the identifiers, decoy and contaminant flags, and recommends `protein_assignment`. `fields()` lists them in `requirement`, and [Sets](sets.md) shows each set's table.

`enforce` checks them once, when the catalog opens:

```python
import polars as pl
from apb_catalog.api import DataCatalog

checked = DataCatalog(diann, "abundance_alpha", "apb_alpha", enforce="recommended")
checked.fields().filter(
    pl.col("level") == "peptidoform_ion", pl.col("requirement").is_not_null()
).select("key", "slot", "requirement", "present")
```

```text
shape: (8, 4)
┌────────────────────┬────────┬─────────────┬─────────┐
│ key                ┆ slot   ┆ requirement ┆ present │
│ ---                ┆ ---    ┆ ---         ┆ ---     │
│ str                ┆ str    ┆ str         ┆ bool    │
╞════════════════════╪════════╪═════════════╪═════════╡
│ intensity          ┆ layers ┆ recommended ┆ true    │
│ peptide            ┆ var    ┆ required    ┆ true    │
│ peptidoform        ┆ var    ┆ required    ┆ true    │
│ peptidoform_ion    ┆ var    ┆ required    ┆ true    │
│ decoy              ┆ var    ┆ required    ┆ true    │
│ contaminant        ┆ var    ┆ required    ┆ true    │
│ protein_assignment ┆ var    ┆ recommended ┆ true    │
│ fasta_accessions   ┆ var    ┆ optional    ┆ true    │
└────────────────────┴────────┴─────────────┴─────────┘
```

| Opened with | `required` absent | `recommended` absent | `optional` absent |
| --- | --- | --- | --- |
| no `enforce` | opens | opens | opens |
| `enforce="required"` | raises `MissingRequiredField` | opens, one logged warning | opens |
| `enforce="recommended"` | raises | raises | opens |

- `MissingRequiredField` lists every missing field, one line each, so an application stops at the start with all of them named, not at its first lookup
- Once the catalog is open, a lookup does not enforce: `get` returns `None` for an absent field
- Which software versions meet a set's requirements, without a result: [Names without data](names.md#requirements-per-software-version)

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

A qualifier the key leaves open is a keyword of `get` and `name`; [Sets](sets.md) lists each set's keys and values.

| Set | Call on the `peptidoform_ion` level | Returns |
| --- | --- | --- |
| `chromatography_alpha` | `layers.get("retention_time", unit="minute")` | DIA-NN `RT` |
| `chromatography_alpha` | `layers.get("retention_time", unit="second")` | DIA-NN `None`: its RT is in minutes |
| `chromatography_alpha` | `layers.get("aligned_retention_time")` | MaxQuant `Calibrated_retention_time` |

- A keyword the key already fixes, such as `stage` with `q_value`, raises `ValueError`
- `[...]` takes no keywords

## When there is no single answer

| Call | Raises |
| --- | --- |
| DIA-NN 1.8 `abundance.levels["protein"].layers.get("intensity_norm_settings")` | `UnresolvedField`, ambiguous: `PG_Normalised` and `PG_MaxLFQ` both are; `aggregation="maxlfq"` picks one |
| Spectronaut `abundance.levels["protein"].layers.get("intensity_norm_settings", aggregation="sum")` | `UnresolvedField`, unknown: `PG_Quantity` leaves aggregation unknown |
| `layers.get("intensity", normalization="none")` | `ValueError`: the key `intensity` fixes normalization |
| `layers["intensities"]` | `KeyError`: no key or field `intensities`; `get` returns `None`, as `dict.get` |

```python
from apb_catalog.api import UnresolvedField

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

confidence = DataCatalog(diann, "confidence_alpha")
confidence.levels["peptidoform_ion"].layers.get("pep")
confidence.levels["peptidoform_ion"].layers.get("q_value")
annotated = attach_snapshot(diann, confidence.snapshot())
write_parsed_levels(annotated, Path("annotated.h5mu"))

record = read_parsed_levels(Path("annotated.h5mu")).metadata["catalog"]["confidence_alpha"]["result"]
stored = ResolutionSnapshot.model_validate(record)
[(r.request.level, r.status, r.reference.name) for r in stored.resolutions]
```

```text
[('peptidoform_ion', 'resolved', 'PEP'), ('peptidoform_ion', 'resolved', 'Q_Value')]
```

The snapshot holds every lookup `confidence` answered, in order.

The snapshot is plain JSON in the result, readable without APB Catalog; [Python API](api.md#snapshots) says where.
