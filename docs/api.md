# Python API

[Examples](examples.md) runs every call below on real results and shows what it returns.

## Lookups on a result

```python
from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

parsed = read_parsed_levels(path)
catalog = DataCatalog(parsed, "confidence")
```

| Call | Returns |
| --- | --- |
| `catalog.layer(level, kind=...)` | The apb2 `FinalLayerTable`, samples × features, or `None` |
| `catalog.var(level, kind=...)` | The var column as a Polars `Series`, or `None` |
| `catalog.obs(level, kind=...)` | The obs column as a Polars `Series`, or `None` |
| `catalog.kinds(level, location)` | The kinds the level offers at `"layers"`, `"var"` or `"obs"`; `()` for none |
| `catalog.fields()` | A Polars `DataFrame` of every catalogued field of the result, `apb-catalog table`'s columns plus `present` and `constant` |

- `kind` may also come second without its keyword: `catalog.layer("peptidoform_ion", "pep")`
- Other qualifiers are keywords too: `DataCatalog(parsed, "abundance").layer("peptidoform_ion", kind="intensity", normalization="none")` returns the layer the software never normalizes
- A level answers only for its own entity: peptidoform_ion for precursors, protein for protein groups
- Per run versus per feature is the choice between `layer` and `var`
- Confidence lookups mean identification; pass `stage="quantification"` for Sage's MS1-peak q-value
- `var` also reads feature-aligned `varm` tables, such as apb-fasta's `fasta_validation`
- In a set whose vocabulary has an `origin` qualifier, `origin=...` chooses where two origins answer one kind
- Misspelled kinds, qualifiers or catalogue names raise `ValueError`
- `fields()` lists a field APB2 left out because it held one value with `present` false and that value as `constant`

## Names without data

```python
from apb_catalog.api import Catalog

Catalog("DIA-NN", "2.6.0", "abundance").layer("peptidoform_ion", kind="intensity", normalization="none").name
# 'Precursor_Quantity'
```

`Catalog(software, version, set)` answers from the software's packaged APB2 rule whose version pattern admits `version`. `layer`, `var` and `obs` return a `Reference` (`level`, `location`, `name`, `table`) or `None`; `kinds` and `fields` work as on a result. A version no packaged rule admits raises `ValueError` naming the patterns. `apb-catalog meaning SET --software DIA-NN --version 2.6.0` prints the same fields.

## Requirements and `enforce`

```python
DataCatalog(parsed, "abundance", enforce="MUST")
```

A set's requirement rows say how strongly a consumer needs a meaning on a level: level, location, kind, other qualifiers and `MUST`, `SHOULD` or `MAY`. `enforce`, on both classes, makes them binding like a log level:

| Created with | MUST absent | SHOULD absent | MAY absent |
| --- | --- | --- | --- |
| no `enforce` | `None` | `None` | `None` |
| `enforce="MUST"` | raises `MissingRequiredField` | `None`, logged warning, summary entry needing attention | `None` |
| `enforce="SHOULD"` | raises | raises | `None` |

- The abundance set's row: `peptidoform_ion`, `layers`, `intensity`, `normalization: none`, SHOULD. apb-export's prolfqua target sets `enforce="MUST"`, so a result without an un-normalized layer exports its primary layer with a warning
- The `apb` set's rows state which levels carry each fixed column
- `enforce` on a set without requirement rows raises `ValueError`

## When there is no single answer

`UnresolvedField` (from `apb_catalog.api`) is raised, naming the reason and the candidates, when:

- two catalogued fields fit equally well, or
- no catalogue variant names the level's software version, for example a new rule version, or a level produced by another tool, or
- the field is apb-fasta's and `apb-fasta verify-peptides` has not run; the message names that command

`StaleField` is raised when the result's stored rule declares the answering field differently from the current packaged rule, or not at all; it names the field and both sources. Anything else in the rule may change. `UnresolvedField` and `StaleField` raise whatever `enforce` says.

`None` means the result lacks the level, or its software version was reviewed and the field is not there.

## Snapshots

```python
from apb_catalog.api import attach_snapshot, stale_levels, stored_snapshot

annotated = attach_snapshot(parsed, catalog.snapshot())   # new result; data shared, not copied
stored_snapshot(annotated, "confidence")                  # read it back
stale_levels(annotated, catalog.snapshot())               # levels whose software name or version changed since
```

The snapshot is stored as JSON at `metadata["catalog"][<set>]["result"]`, beside other sets' snapshots, with each level's request counts in that level's `metadata["catalog"][<set>]["summary"]`. Both persist in h5ad, h5mu, Parquet and DuckDB. It embeds the set's description, its vocabulary, level bindings, catalogued fields and every answer, so a reader needs neither this package nor its catalogues. Its JSON Schema ships as `apb_catalog/data/apb-catalog-resolution-0.5.schema.json`.

## The long table

```python
from apb_catalog.api import catalogue_table

catalogue_table()           # every set; catalogue_table("apb") for one
```

One row per entry and rule it applies to: `set`, `source` (the vendor, `producer:<name>` or `annotation:<convention>`), `version_pattern`, `rule` (`*` for an entry of every rule), `level`, `location`, `table`, `name` (`role:<role>` or `prefix:<prefix>` for a field found by role or column-name prefix), one `qualifier.<name>` column per qualifier, `requirement` and `entry_id`. A row is identified by `set`, `entry_id` and `rule`. `apb-catalog table [SET] [--output PATH]` writes it as CSV.

## Rule check

```python
from apb_catalog.api import catalogues, rule_coverage

catalogues()                # one row per set: purpose, users, entries, whether it sets requirements
rule_coverage("confidence")   # one row per field of every packaged rule level
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

- Requirement rows live in `src/apb_catalog/data/requirements.json`, per set, or in a plugin set's own `requirements.json`; the abundance and `apb` sets set them
- APB2's fields count where the rule's level keeps their column; apb-fasta's count on every level, with `needs`
- A set without vendor catalogues, such as `apb`, is checked against every packaged rule level
- A level with no catalogued or required field has one row without a kind
- The command line prints the same check: `apb-catalog check SET`, or `apb-catalog check SET spectronaut` for one vendor's fields; it exits 1 when a level fails
