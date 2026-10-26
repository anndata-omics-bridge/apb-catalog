# Examples

Every call of the [Python API](api.md), run on APB2 results of four ProteoBench submissions converted to h5mu: `DIA-NN` 2.6.0, `MaxQuant` 2.8.1.0, `Spectronaut` 20 and `Sage` 0.15. The outputs are what the calls returned on 23 October 2026.

## Open a catalog

```python
from pathlib import Path

from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

result = read_parsed_levels(Path("converted.h5mu"))   # DIA-NN 2.6.0
abundance = DataCatalog(result, "abundance")
```

The second argument names the catalogue set: `abundance`, `confidence`, `proteobench_entrapment` or `apb`.

## Ask which kinds a level offers

`kinds` lists the kinds a level offers at one location, given the other qualifiers:

```python
abundance.kinds("peptidoform_ion", "layers")                         # ('intensity', 'ms1_intensity')
abundance.kinds("peptidoform_ion", "layers", normalization="none")   # ('intensity', 'ms1_intensity'): both have an unnormalized layer
abundance.kinds("protein", "layers")                     # ('unknown',): PG_MaxLFQ's kind is not settled
```

## Get one layer

```python
layer = abundance.layer("peptidoform_ion", kind="intensity", normalization="none")
layer.layer_name    # 'Precursor_Quantity'
layer.wide().head(3)
```

```text
┌────────────┬────────────┬───────────┬────────────┬───────────┬────────────┐
│ obs_0      ┆ obs_1      ┆ obs_2     ┆ obs_3      ┆ obs_4     ┆ obs_5      │
╞════════════╪════════════╪═══════════╪════════════╪═══════════╪════════════╡
│ 4.261315e6 ┆ 4.994219e6 ┆ 4248348.5 ┆ 4.439875e6 ┆ 4368628.5 ┆ 5047983.5  │
│ 887880.625 ┆ 1.1896e6   ┆ 1068317.5 ┆ 1292125.5  ┆ 1.2170e6  ┆ NaN        │
│ 3.9066e6   ┆ 3.3759e6   ┆ 3.3533e6  ┆ 3.807868e6 ┆ 3.7494e6  ┆ 3.761085e6 │
└────────────┴────────────┴───────────┴────────────┴───────────┴────────────┘
```

`kind` may come second without its keyword, and every other qualifier is a keyword:

```python
abundance.layer("peptidoform_ion", "intensity", normalization="none").layer_name          # 'Precursor_Quantity'
abundance.layer("peptidoform_ion", kind="intensity", normalization="run_setting").layer_name   # 'Precursor_Normalised'
```

The same call answers for every quantification tool:

```python
DataCatalog(maxquant, "abundance").layer("peptidoform_ion", kind="intensity", normalization="none").layer_name
# 'Intensity'
```

## Per run or per feature: `layer` and `var`

A layer holds one value per run and feature; a `var` column one value per feature.

```python
confidence = DataCatalog(result, "confidence")    # DIA-NN 2.6.0
confidence.kinds("peptidoform_ion", "layers")                                      # ('pep', 'q_value')
confidence.kinds("peptidoform_ion", "var")                                        # ('global_q_value',)
confidence.layer("peptidoform_ion", kind="q_value").layer_name           # 'Q_Value', one per run
confidence.var("peptidoform_ion", kind="global_q_value").name            # 'Global_Q_Value', one per precursor
confidence.layer("protein", kind="q_value").layer_name       # 'PG_Q_Value'
confidence.var("protein", kind="global_q_value").name        # 'Global_PG_Q_Value'
```

`Spectronaut` 20 also reports the global protein q-value once per protein group:

```python
confidence = DataCatalog(spectronaut, "confidence")
confidence.kinds("protein", "layers")                                  # ('q_value',)
confidence.kinds("protein", "var")                                    # ('global_q_value',)
confidence.layer("protein", kind="q_value").layer_name       # 'PG_QValue_Run_Wise'
confidence.var("protein", kind="global_q_value").head(3)
```

```text
shape: (3,)
Series: 'PG_Qvalue' [f64]
[
	0.0
	0.00172
	0.000674
]
```

`MaxQuant` 2.8.1.0 has per-feature fields on several levels:

```python
confidence = DataCatalog(maxquant, "confidence")
confidence.kinds("protein", "var")    # ('global_q_value',)
confidence.kinds("peptide", "var")    # ('pep',)
```

## A qualifier with a default: `stage`

Confidence lookups mean identification unless `stage` says otherwise. `Sage` 0.15 reports only a quantification q-value, the q-value of its MS1 peak:

```python
confidence = DataCatalog(sage, "confidence")
confidence.kinds("peptidoform_ion", "var")                                                      # ()
confidence.kinds("peptidoform_ion", "var", stage="quantification")                    # ('q_value',)
confidence.var("peptidoform_ion", kind="q_value", stage="quantification").name         # 'Q_Value'
```

## Names without data: `Catalog`

The software and version stand in for the result; the packaged rule whose version pattern admits the version decides:

```python
from apb_catalog.api import Catalog

Catalog("DIA-NN", "2.6.0", "abundance").layer("peptidoform_ion", kind="intensity", normalization="none").name
# 'Precursor_Quantity'
Catalog("DIA-NN", "2.6.0", "apb").var("peptidoform_ion", kind="protein_assignment").name
# 'Protein_Group'
```

## Everything a result holds: `fields()`

```python
fields = Catalog("DIA-NN", "2.6.0", "confidence").fields()
fields.select("level", "location", "name", "qualifier.kind", "qualifier.stage", "present")
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

On a result, `DataCatalog(result, "confidence").fields()` has the same columns; a field APB2 left out because it held one value has `present` false and that value as `constant`.

## The entrapment set

`apb-proteobench` asks this set for every precursor q-value it can score:

```python
DataCatalog(result, "proteobench_entrapment").kinds("peptidoform_ion", "layers")         # ('q_value',)
DataCatalog(result, "proteobench_entrapment").kinds("peptidoform_ion", "var")           # ('global_q_value', 'library_q_value')
DataCatalog(spectronaut, "proteobench_entrapment").kinds("peptidoform_ion", "layers")    # ('q_value',)
DataCatalog(maxquant, "proteobench_entrapment").kinds("peptidoform_ion", "layers")       # (): no entry for MaxQuant
```

## When there is no single answer

```python
from apb_catalog.api import UnresolvedField

try:
    abundance.layer("peptidoform_ion", kind="intensity")
except UnresolvedField as error:
    print(error)
```

| Call | Raises |
| --- | --- |
| `DIA-NN`: `abundance.layer("peptidoform_ion", kind="intensity")` | `UnresolvedField`: ambiguous, 2 entries match: `Precursor_Quantity`, `Precursor_Normalised` |
| `Spectronaut` 20: `abundance.layer("peptidoform_ion", kind="intensity", normalization="none")` | `UnresolvedField`: unknown, `EG_TotalQuantity_Settings` (and two more) leave normalization unknown |
| `DIA-NN` 2.6.0: `abundance.layer("protein", kind="maxlfq")` | `UnresolvedField`: unknown, `PG_MaxLFQ` leaves kind unknown |
| `abundance.layer("peptidoform_ion", kind="intensity", normalisation="none")` | `ValueError`: unknown qualifier `normalisation`; declared: `kind`, `normalization` |
| `abundance.layer("peptidoform_ion", kind="intensities")` | `ValueError`: qualifier `kind` does not admit `intensities`, with the admitted kinds |

## Record what was looked up

```python
from apb2.api import write_parsed_levels
from apb_catalog.api import attach_snapshot, stale_levels, stored_snapshot

confidence = DataCatalog(result, "confidence")
q_value = confidence.layer("peptidoform_ion", kind="q_value")
annotated = attach_snapshot(result, confidence.snapshot())
write_parsed_levels(annotated, Path("annotated.h5mu"))

stored = stored_snapshot(read_parsed_levels(Path("annotated.h5mu")), "confidence")
[(r.request.level, r.status, r.reference.name) for r in stored.resolutions]
# [('peptidoform_ion', 'resolved', 'Q_Value')]

stale_levels(annotated, confidence.snapshot())    # (): software name and version unchanged
stale_levels(annotated, DataCatalog(maxquant, "confidence").snapshot())
# ('peptidoform_ion', 'peptidoform', 'peptide', 'protein'): levels whose software name or version differ
```

## Catalogue-wide tables

```python
from apb_catalog.api import catalogues, rule_coverage

catalogues()                   # 3 rows: abundance (48 entries), confidence (20), proteobench_entrapment (7)
rule_coverage("abundance")     # 71 rows × 15 columns, one per field of every packaged rule level
```

```text
┌──────────┬─────────┬───────┬───────────────┬───────────────────────────┬──────────────────────┐
│ software ┆ version ┆ level ┆ kind          ┆ qualifiers                ┆ column               │
╞══════════╪═════════╪═══════╪═══════════════╪═══════════════════════════╪══════════════════════╡
│ DIA-NN   ┆ 1.0–1.7 ┆ ion   ┆ intensity     ┆ normalization=none        ┆ Precursor_Quantity   │
│ DIA-NN   ┆ 1.0–1.7 ┆ ion   ┆ intensity     ┆ normalization=run_setting ┆ Precursor_Normalised │
│ DIA-NN   ┆ 1.0–1.7 ┆ ion   ┆ ms1_intensity ┆ normalization=none        ┆ Ms1_Area             │
│ DIA-NN   ┆ 1.8–1.9 ┆ ion   ┆ intensity     ┆ normalization=none        ┆ Precursor_Quantity   │
│ DIA-NN   ┆ 1.8–1.9 ┆ ion   ┆ intensity     ┆ normalization=run_setting ┆ Precursor_Normalised │
│ DIA-NN   ┆ 1.8–1.9 ┆ ion   ┆ ms1_intensity ┆ normalization=none        ┆ Ms1_Area             │
└──────────┴─────────┴───────┴───────────────┴───────────────────────────┴──────────────────────┘
```

The command line prints the same catalog as one table: `apb-catalog meaning abundance`.
