# Examples

Every call of the [Python API](api.md), run on APB2 results of four ProteoBench submissions converted to h5mu: `DIA-NN` 2.6.0, `MaxQuant` 2.8.1.0, `Spectronaut` 20 and `Sage` 0.15. The outputs are what the calls returned on 23 October 2026.

## Open a catalog

```python
from pathlib import Path

from apb2.api import read_parsed_levels
from apb_catalog.api import Catalog

result = read_parsed_levels(Path("converted.h5mu"))   # DIA-NN 2.6.0
abundance = Catalog(result, "abundance")
```

The second argument names the catalogue set: `abundance`, `identification_confidence` or `proteobench_entrapment`. Each set has one concept, so calls need not name it.

## Ask which kinds a level offers

Without `kind`, a call returns the kinds on offer instead of a field:

```python
abundance.layer("peptidoform_ion")                         # ('intensity', 'ms1_intensity')
abundance.layer("peptidoform_ion", normalization="none")   # ('intensity', 'ms1_intensity'): both have an unnormalized layer
abundance.layer("protein")                     # ('unknown',): PG_MaxLFQ's kind is not settled
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
Catalog(maxquant, "abundance").layer("peptidoform_ion", kind="intensity", normalization="none").layer_name
# 'Intensity'
```

## Per run or per feature: `layer` and `var`

A layer holds one value per run and feature; a `var` column one value per feature.

```python
confidence = Catalog(result, "identification_confidence")    # DIA-NN 2.6.0
confidence.layer("peptidoform_ion")                                      # ('pep', 'q_value')
confidence.var("peptidoform_ion")                                        # ('global_q_value',)
confidence.layer("peptidoform_ion", kind="q_value").layer_name           # 'Q_Value', one per run
confidence.var("peptidoform_ion", kind="global_q_value").name            # 'Global_Q_Value', one per precursor
confidence.layer("protein", kind="q_value").layer_name       # 'PG_Q_Value'
confidence.var("protein", kind="global_q_value").name        # 'Global_PG_Q_Value'
```

`Spectronaut` 20 also reports the global protein q-value once per protein group:

```python
confidence = Catalog(spectronaut, "identification_confidence")
confidence.layer("protein")                                  # ('q_value',)
confidence.var("protein")                                    # ('global_q_value',)
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
confidence = Catalog(maxquant, "identification_confidence")
confidence.var("protein")    # ('global_q_value',)
confidence.var("peptide")    # ('pep',)
```

## A qualifier with a default: `stage`

Confidence lookups mean identification unless `stage` says otherwise. `Sage` 0.15 reports only a quantification q-value, the q-value of its MS1 peak:

```python
confidence = Catalog(sage, "identification_confidence")
confidence.var("peptidoform_ion")                                                      # None
confidence.var("peptidoform_ion", stage="quantification")                              # ('q_value',)
confidence.var("peptidoform_ion", kind="q_value", stage="quantification").name         # 'Q_Value'
```

## Name the concept explicitly

`concept=` is needed only for a plugin set whose entries name several concepts; there, omitting it raises `ValueError`. For the packaged sets it changes nothing:

```python
Catalog(result, "identification_confidence").layer("peptidoform_ion", kind="q_value", concept="confidence").layer_name
# 'Q_Value'
```

## Everything a result holds: `fields()`

```python
Catalog(result, "identification_confidence").fields()    # DIA-NN 2.6.0
```

```text
┌─────────┬──────────┬───────┬───────────────────┬────────────┬─────────────────┬────────────────┐
│ level   ┆ location ┆ table ┆ name              ┆ concept    ┆ kind            ┆ stage          │
╞═════════╪══════════╪═══════╪═══════════════════╪════════════╪═════════════════╪════════════════╡
│ ion     ┆ layers   ┆ null  ┆ Q_Value           ┆ confidence ┆ q_value         ┆ identification │
│ ion     ┆ layers   ┆ null  ┆ PEP               ┆ confidence ┆ pep             ┆ identification │
│ ion     ┆ var      ┆ null  ┆ Global_Q_Value    ┆ confidence ┆ global_q_value  ┆ identification │
│ protein ┆ layers   ┆ null  ┆ PG_Q_Value        ┆ confidence ┆ q_value         ┆ identification │
│ protein ┆ var      ┆ null  ┆ Lib_PG_Q_Value    ┆ confidence ┆ library_q_value ┆ identification │
│ protein ┆ var      ┆ null  ┆ Global_PG_Q_Value ┆ confidence ┆ global_q_value  ┆ identification │
└─────────┴──────────┴───────┴───────────────────┴────────────┴─────────────────┴────────────────┘
```

## The entrapment set

`apb-proteobench` asks this set for every precursor q-value it can score:

```python
Catalog(result, "proteobench_entrapment").layer("peptidoform_ion")         # ('q_value',)
Catalog(result, "proteobench_entrapment").var("peptidoform_ion")           # ('global_q_value', 'library_q_value')
Catalog(spectronaut, "proteobench_entrapment").layer("peptidoform_ion")    # ('q_value',)
Catalog(maxquant, "proteobench_entrapment").layer("peptidoform_ion")       # None: no entry for MaxQuant
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

confidence = Catalog(result, "identification_confidence")
q_value = confidence.layer("peptidoform_ion", kind="q_value")
annotated = attach_snapshot(result, confidence.snapshot())
write_parsed_levels(annotated, Path("annotated.h5mu"))

stored = stored_snapshot(read_parsed_levels(Path("annotated.h5mu")), "identification_confidence")
[(r.request.level, r.status, r.reference.name) for r in stored.resolutions]
# [('peptidoform_ion', 'resolved', 'Q_Value')]

stale_levels(annotated, confidence.snapshot())    # (): software name and version unchanged
stale_levels(annotated, Catalog(maxquant, "identification_confidence").snapshot())
# ('peptidoform_ion', 'peptidoform', 'peptide', 'protein'): levels whose software name or version differ
```

## Catalogue-wide tables

```python
from apb_catalog.api import catalogues, rule_coverage

catalogues()                   # 3 rows: abundance (48 entries), identification_confidence (20), proteobench_entrapment (7)
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
