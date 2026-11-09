# Contributing

The catalog can be extended to suit your application. New terms are supported by adding catalog entries, without changing APB2's parser, and you are welcome to create catalogs of your own. Together with APB2's tested parsing rules, the catalogs are meant as a community resource on what quantification software reports and how applications use it.

## What a catalog is

A catalogue set covers one topic, such as `abundance_alpha` or `confidence_alpha`:

| Part | Holds | Example |
| --- | --- | --- |
| Terms | The root, `terms.csv`: the names an application asks by, at each level and location, with the kind each stands for, the qualifier values it fixes and, optionally, how strongly the application needs it: `required`, `recommended` or `optional` | `intensity` at `peptidoform_ion/layers`: an intensity without normalization, recommended |
| Kinds | What a term measures; always known | `intensity`, `ibaq` |
| Qualifiers | Optional: what refines a kind, each with its values, `unknown` among them once there are any | `normalization`: `none` or `run_setting`; `aggregation`: `sum` or `maxlfq` |
| Entries | For each software version, the column that holds a term, with the tool's documentation as evidence | DIA-NN 2.x: `Precursor_Quantity` |

Two people fill a set:

- the application developer writes the terms the application needs, and how strongly, before any software maps them; a term no entry maps yet loads with a warning
- the integrator writes the entries for each software version and quotes the tool's documentation

`apb-catalog check SET` then reports, for every software version APB2 converts, which required or recommended terms it lacks. The [catalog viewer](https://fgcz-ms.uzh.ch/public/apb-catalog/) shows every set in the browser.

## Ways to contribute

| You want | Do |
| --- | --- |
| A software version or a field a set lacks | Add its entries by pull request; see [An entry](maintaining.md#an-entry) |
| An entry corrected | Open an issue or a pull request with the evidence |
| Terms for your application, from Python, R and TypeScript | Add a set to apb-catalog by pull request; see [Adding a set](maintaining.md#adding-a-set) |
| A catalog released with your own application | A plugin set in your package; see below |

## A catalog of your own

A Python package adds a set without changing apb-catalog: the same CSV tables with only its rows, registered as an entry point:

```toml
[project.entry-points."apb_catalog.catalogues"]
peak_qc = "peak_qc_app.catalogue"
```

- `DataCatalog(result, "peak_qc")`, `rule_coverage("peak_qc")` and `apb-catalog check peak_qc` work as for a packaged set
- the set stays yours: you release and version it with your application, and it can be private
- Python only: plugin sets never enter the bundle that apbCatalogR and apb-catalog-ts read; for R and TypeScript, contribute the set to apb-catalog
- [Plugin sets](maintaining.md#plugin-sets) has the details

## A mini example: two tools

A peak-shape QC app needs each ion's retention time and, if the software reports it, its peak width. The set `peak_qc` catalogues both for DIA-NN and FragPipe, in six files in the package folder `peak_qc_app/catalogue/`. Every row of every file starts with the set's name, `peak_qc`; the tables leave that column out, and the CSV file under each table has it.

`sets.csv` holds the set's one row: its prefix, what its fields are, what its kinds name, its purpose and its users. The prefix asks this set alone, as `pqc:retention_time`; `v` is reserved, and no two sets share one.

| `prefix` | `definition` | `kind_definition` | `purpose` | `used_by` |
| --- | --- | --- | --- | --- |
| `pqc` | Retention time and peak width of an ion in one run. | Which quantity the value is. | Peak-shape QC: where each ion eluted, and how wide its peak was. | peak-qc app |

<details markdown>
<summary>The CSV file: <code>sets.csv</code></summary>

```csv
set,prefix,definition,kind_definition,purpose,used_by
peak_qc,pqc,Retention time and peak width of an ion in one run.,Which quantity the value is.,"Peak-shape QC: where each ion eluted, and how wide its peak was.",peak-qc app
```

</details>

`terms.csv` is where the set starts: the terms the app asks for, before any software maps them. Each is a key at one location, `<level>/<attribute>`, with the kind it stands for and how strongly the app needs it. A key that fixes a qualifier value, such as abundance's `intensity` with `normalization` `none`, has one row per fixed value; these keys fix none, so `qualifier` and `value` stay empty. `catalog.csv` may map no other term.

| `location` | `key` | `kind` | `qualifier` | `value` | `requirement` | `definition` |
| --- | --- | --- | --- | --- | --- | --- |
| `peptidoform_ion/layers` | `retention_time` | `retention_time` | | | `required` | Where the ion eluted in this run. |
| `peptidoform_ion/layers` | `peak_fwhm` | `peak_fwhm` | | | `recommended` | The width of the ion's elution peak at half maximum. |

<details markdown>
<summary>The CSV file: <code>terms.csv</code></summary>

```csv
set,location,key,kind,qualifier,value,requirement,psi_ms,definition
peak_qc,peptidoform_ion/layers,retention_time,retention_time,,,required,,Where the ion eluted in this run.
peak_qc,peptidoform_ion/layers,peak_fwhm,peak_fwhm,,,recommended,,The width of the ion's elution peak at half maximum.
```

</details>

`kinds.csv` holds what a field of the set can be; a set declared in `sets.csv` alone, while it is planned, needs no kinds yet.

| `kind` | `definition` |
| --- | --- |
| `retention_time` | Where the ion eluted in this run: the apex of its elution peak. |
| `peak_fwhm` | The width of the elution peak at half its maximum height. |

<details markdown>
<summary>The CSV file: <code>kinds.csv</code></summary>

```csv
set,kind,definition
peak_qc,retention_time,Where the ion eluted in this run: the apex of its elution peak.
peak_qc,peak_fwhm,The width of the elution peak at half its maximum height.
```

</details>

`qualifiers.csv` holds what refines a kind; here the unit, which a set without qualifiers leaves out.

| `qualifier` | `definition` |
| --- | --- |
| `unit` | The time unit of the value. |

<details markdown>
<summary>The CSV file: <code>qualifiers.csv</code></summary>

```csv
set,qualifier,definition
peak_qc,unit,The time unit of the value.
```

</details>

`qualifier_values.csv` holds the values each qualifier admits, `unknown` among them once it admits any.

| `qualifier` | `value` | `definition` |
| --- | --- | --- |
| `unit` | `minute` | Minutes. |
| `unit` | `second` | Seconds. |
| `unit` | `unknown` | The reviewer could not establish this. |

<details markdown>
<summary>The CSV file: <code>qualifier_values.csv</code></summary>

```csv
set,qualifier,value,definition
peak_qc,unit,minute,Minutes.
peak_qc,unit,second,Seconds.
peak_qc,unit,unknown,The reviewer could not establish this.
```

</details>

`catalog.csv` maps the terms to columns: one row per column a software writes and qualifier of its set; this set has one qualifier, so one row per column. `software`, `location` and `name` say where the column lives, as `<software>/<version>`, `<level>/<attribute>` and `<key>/<column>` (see [An entry](maintaining.md#an-entry)); then come the term's key and kind, its value of the set's qualifier, here the unit, whether the key fixes that value, the key's PSI-MS terms, left empty here, and the evidence; key, kind, `fixed` and PSI-MS terms repeat `terms.csv`, so each row reads alone. Version `*` holds for every version; DIA-NN reports `FWHM` only from 2.x, so that entry names the label `2.x`. Neither key fixes the unit, so `fixed` is `false`; a key whose term fixes one, such as abundance's `intensity_norm_settings` with `normalization` `run_setting`, is `true` on every row of that qualifier.

| `software` | `location` | `name` | `key` | `kind` | `qualifier` | `value` | `fixed` | `basis` | `evidence_url` |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `DIA-NN/*` | `peptidoform_ion/layers` | `RT/-` | `retention_time` | `retention_time` | `unit` | `minute` | `false` | DIA-NN README: the observed precursor retention time, in minutes. | [DIA-NN README](https://github.com/vdemichev/DiaNN#main-output-reference) |
| `DIA-NN/2.x` | `peptidoform_ion/layers` | `FWHM/-` | `peak_fwhm` | `peak_fwhm` | `unit` | `minute` | `false` | DIA-NN README: the estimated peak width at half maximum, in minutes. | [DIA-NN README](https://github.com/vdemichev/DiaNN#main-output-reference) |
| `FragPipe/*` | `peptidoform_ion/layers` | `Apex_Retention_Time/-` | `retention_time` | `retention_time` | `unit` | `unknown` | `false` | FragPipe outputs: the retention time of the precursor's apex intensity; the unit depends on the instrument. | [FragPipe outputs](https://fragpipe.nesvilab.org/docs/tutorial_fragpipe_outputs.html) |
| `FragPipe/*` | `peptidoform_ion/layers` | `Retention_Time_FWHM/-` | `peak_fwhm` | `peak_fwhm` | `unit` | `unknown` | `false` | FragPipe outputs: the width of the precursor's elution peak at half maximum; the unit depends on the instrument. | [FragPipe outputs](https://fragpipe.nesvilab.org/docs/tutorial_fragpipe_outputs.html) |

<details markdown>
<summary>The CSV file: <code>catalog.csv</code></summary>

```csv
set,software,location,name,key,kind,qualifier,value,fixed,psi_ms,basis,evidence_url
peak_qc,DIA-NN/*,peptidoform_ion/layers,RT/-,retention_time,retention_time,unit,minute,false,,"DIA-NN README: the observed precursor retention time, in minutes.",https://github.com/vdemichev/DiaNN#main-output-reference
peak_qc,DIA-NN/2.x,peptidoform_ion/layers,FWHM/-,peak_fwhm,peak_fwhm,unit,minute,false,,"DIA-NN README: the estimated peak width at half maximum, in minutes.",https://github.com/vdemichev/DiaNN#main-output-reference
peak_qc,FragPipe/*,peptidoform_ion/layers,Apex_Retention_Time/-,retention_time,retention_time,unit,unknown,false,,"FragPipe outputs: the retention time of the precursor's apex intensity; the unit depends on the instrument.",https://fragpipe.nesvilab.org/docs/tutorial_fragpipe_outputs.html
peak_qc,FragPipe/*,peptidoform_ion/layers,Retention_Time_FWHM/-,peak_fwhm,peak_fwhm,unit,unknown,false,,"FragPipe outputs: the width of the precursor's elution peak at half maximum; the unit depends on the instrument.",https://fragpipe.nesvilab.org/docs/tutorial_fragpipe_outputs.html
```

</details>

`producers.csv` is left out; it names apps, such as apb-fasta, whose fields exist only after they have run.

The app then asks by key:

<!-- not run: peak_qc is the plugin set this page builds, not installed -->
```python
from apb_catalog.api import Catalog

Catalog("DIA-NN", "2.2.0", "peak_qc").levels["peptidoform_ion"].layers.get("peak_fwhm")  # 'FWHM'
Catalog("DIA-NN", "1.9.2", "peak_qc").levels["peptidoform_ion"].layers.get("peak_fwhm")  # None
Catalog("FragPipe", "23.0", "peak_qc").levels["peptidoform_ion"].layers.get("retention_time")  # 'Apex_Retention_Time'
```

The check shows what each DIA-NN version supplies:

```console
$ apb-catalog check peak_qc dia-nn
WARN  DIA-NN 1.0–1.7 peptidoform_ion: missing peak_fwhm recommended
    retention_time [unit=minute] required: RT
    peak_fwhm recommended: missing
WARN  DIA-NN 1.8–1.9 peptidoform_ion: missing peak_fwhm recommended
    retention_time [unit=minute] required: RT
    peak_fwhm recommended: missing
PASS  DIA-NN 2.x peptidoform_ion
    retention_time [unit=minute] required: RT
    peak_fwhm [unit=minute] recommended: FWHM
```

A set with entries for some tools reviews them only. `apb-catalog check peak_qc` fails every level of the tools it has no entries for, and their lookups find nothing.

## Kinds, qualifiers and keys

A kind says what a field is; it is part of an entry's identity, so one column with two meanings is two entries. A qualifier such as `unit` refines a kind, and every entry gives each qualifier a value, `unknown` where the evidence does not establish one. A key names one kind and may fix a value of each qualifier; every entry names its key and carries the values its key fixes.

An app that wants minutes need not change the keys; it narrows the lookup instead:

| Lookup | DIA-NN 2.2 | FragPipe 23 |
| --- | --- | --- |
| `get("retention_time")` | `RT` | `Apex_Retention_Time` |
| `get("retention_time", unit="minute")` | `RT` | unknown: FragPipe does not state its unit |

A key that fixes the unit is a different matter. Added beside `retention_time`, a key `retention_time_minutes` whose rows fix `unit` `minute` answers only for the fields whose rows name it: each field names one key, and a lookup by key returns that key's fields. Fix a qualifier in a key only when it changes the meaning enough that an app asks for it by name, as abundance's `intensity_ms1` fixes `ms_level` `ms1`.

## Getting started

- See what exists in the [catalog viewer](https://fgcz-ms.uzh.ch/public/apb-catalog/) and on [Catalogues](catalogues.md)
- Open an [issue](https://github.com/anndata-omics-bridge/apb-catalog/issues) naming your application, the terms it needs and how strongly
- A pull request runs `make check`, whose tests compare every entry with APB2's packaged rules
