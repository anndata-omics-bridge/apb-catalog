# Python API

Everything is imported from `apb_catalog.api`, except the pandas `DataCatalog`, which `apb_catalog.api_pandas` holds ([pandas](#pandas)). [Get started](getting-started.md) shows each call on real results.

## Catalogs

| Constructor | Answers from |
| --- | --- |
| `DataCatalog(result, *catalogs, enforce=None)` | An apb2 `ParsedLevels` result: the rule each level was converted with; the named sets alone, so `apb_alpha`, the fields `apb2 convert` writes, answers only when named |
| `Catalog(software, version, catalog, enforce=None)` | The packaged APB2 rule whose version pattern admits `version`; no data |

| Member | `DataCatalog` | `Catalog` |
| --- | --- | --- |
| `levels[name]` | one result level with AnnData's slots, looked up by key; see [Levels](#levels) | one rule level with the same slots, holding names |
| `fields()` | Polars `DataFrame`: the [long table](#the-long-table)'s columns plus `present`, `constant` | same |
| `snapshot(catalog=None)` | `ResolutionSnapshot` of one set's lookups so far; the first set named by default; `ValueError` when no set is named | — |
| `resolve(request)` | `Resolution` of one explicit request, recorded for the snapshot: status `resolved`, `missing`, `ambiguous` or `unknown`, with candidates and reasons; an undecided answer is a status, not an `UnresolvedField` | — |
| `description` | the first set named: its `purpose` and `used_by` | same |
| `DataCatalog.answering_sets(result)` | the sets `DataCatalog(result, name)` opens, a `list[str]`: every packaged and plugin set but one whose app has not run on the result or whose annotation it does not record; a static method, so nothing raises | — |

- A key is one of the set's keys, listed per set in [Catalogues](catalogues.md): a kind with the qualifier values it fixes, such as `intensity_norm_settings` (kind `intensity`, normalization `run_setting`)
- A slot's `get` and `name` take `**qualifiers`, a qualifier the key leaves open, such as `unit`; `kind`, or a qualifier the key fixes, raises `ValueError`
- `resolve` takes a request naming a level, optionally a location and a key, and the accepted values of each qualifier; `apb_catalog.api` exports neither its type, `FieldRequest`, nor `Resolution`
- A level's `var` also reads feature-aligned `varm` tables, such as apb-fasta's `fasta_validation`, which `fasta_peptides_alpha` catalogues
- `fields()` lists a field APB2 left out because it held one value with `present` false and that value as `constant`
- A level answers only for its own entity: `peptidoform_ion` for precursors, `protein` for protein groups
- Composed sets: a key routes to the sets that define it; two sets naming different fields for one key on one level raise `ValueError` when the catalog is built; a slot's `keys()` and `fields()` cover every set; `enforce` checks each set's requirements when the catalog opens
- With no set named, every name is the level's own, as in AnnData

## Levels

`DataCatalog(result, "abundance_alpha", "confidence_alpha").levels["protein"]` has AnnData's slots and returns what AnnData returns, with polars in place of pandas; the pandas `DataCatalog` returns AnnData's own values, and `Catalog`'s levels hold names:

| Slot | `DataCatalog` | pandas `DataCatalog` | `Catalog` |
| --- | --- | --- | --- |
| `X` | numpy matrix, runs × features: the level's primary layer | AnnData's `X` | — |
| `layers[key]` | numpy matrix, runs × features | the matrix AnnData holds | `str`, the layer's name |
| `var[key]`, `obs[key]` | polars `Series`; `var` also reads `varm` tables | pandas `Series` | `str` |
| `var[[key, …]]`, `obs[[key, …]]` | polars `DataFrame` of every column the keys name, in order; a `varm` column is named `table/column` | pandas `DataFrame` | `tuple[str, ...]` |
| `get(key, **qualifiers)` on a slot | the value, or `None` where `[key]` raises `KeyError`; qualifiers the key leaves open narrow it, such as `unit="minute"` | same | `str` or `None` |
| `name(key, **qualifiers)` on a slot | `str`: the name of the field `get` reads, such as `'PEP'`; a `varm` field `table/column`; `KeyError` when there is none | same | same |
| `obs_names`, `var_names` | polars `Series` of strings: the key columns, joined by `\|` | AnnData's own index | — |
| `keys()` on a slot | `set[str]`: the keys the level offers there | same | same |

- Lookup follows cf_xarray: a key first, then the level's own name in that slot, else `KeyError`; `UnresolvedField` when the key names several fields or one the catalogue cannot decide
- Past the mapping, a slot answers as scverse AnnData's does: `get` returns `None` where `adata.var.get` and `adata.layers.get` do, and `[...]` raises `KeyError` where AnnData raises it. The catalog adds no error or default of its own, so a key of a set not named, such as `chromatography_alpha`'s `aligned_peak_end` in a catalog of `confidence_alpha`, is `None` from `get`; the caller handles it
- A prefix makes the lookup exact, since a vendor may name a column as a key is named: a set's prefix asks that set alone, so `c:q_value` is the confidence set's q-value or nothing, never Sage's own `q_value` column; `v:` asks the level's own name alone, so `v:q_value` is that column, never the catalog. `catalogues()` lists each set's `prefix`; `v` is reserved
- A list reads every field a key names, as cf_xarray's `ds.cf[["name"]]`: both contaminant flags where the vendor and apb-fasta each set one, every prolfquapp `group` column; it still raises `UnresolvedField` for a field the catalogue cannot decide
- `keys()` and `in` know keys only; vendor names are read, not listed
- Every key `keys()` lists reads: an app's keys, such as apb-fasta's `fasta_matches_contaminant`, are there once the app has run. `DataCatalog(result, "fasta_peptides_alpha")` on a result apb-fasta has not verified raises `ValueError` when it opens, naming what to run; `DataCatalog.answering_sets(result)` says beforehand which sets open
- A key may name the primary layer and then answers `X`; `layers` holds the other layers, as in AnnData
- A matrix is built once per level and shared by every later answer

`Catalog("DIA-NN", "2.6.0", "abundance_alpha").levels["peptidoform_ion"].layers["intensity"]` is `'Precursor_Quantity'`. Without data there is no `X`, `obs_names`, `var_names` or own name: a name that is no key the level answers raises `KeyError`, and so does every `v:` name.

## pandas

`from apb_catalog.api_pandas import DataCatalog` is the one module beside `apb_catalog.api`, for the AnnData or MuData object APB2 wrote:

- `DataCatalog(data, *catalogs, enforce=None)`: `data` read with `mudata.read_h5mu` or, for one level, `anndata.read_h5ad`; `ValueError` for an object without `uns["apb"]`
- The lookup is `api.DataCatalog`'s: the same keys, names, `None`, `KeyError` and `UnresolvedField`; only the values are AnnData's
- Own names are APB2's: `layers["a/b"]` reads the layer AnnData stores as `a_b`
- Levels only: `fields()`, `snapshot()`, `resolve()` and `description` stay on `api.DataCatalog`
- `DataCatalog.answering_sets(data)`: the same sets as `api.DataCatalog.answering_sets`, read from the object's APB2 record
- `as_mudata()`: a new MuData of the catalogued fields alone, each under its key, with `uns["catalog"]` recording each column; `levels[name].as_anndata()` converts one level ([A result named by catalog keys](keyed.md))

## Answers

| Answer | Means |
| --- | --- |
| a field | Exactly one catalogued field matches |
| `None` | From `get`: the level's software version was reviewed and has no such field, or the name is neither a key nor the level's own; an absent level is not in `levels` |
| `KeyError` | From `[...]` and `name` where `get` returns `None` |
| `UnresolvedField` | Two fields match equally, an entry leaves a requested qualifier `unknown`, no catalogue reviewed the level's software version, or an app a plugin set also names has not run, in `Catalog` or in a set with vendor entries too; names the reason and candidates |
| `ValueError` | A misspelled set or qualifier, qualifiers with a name that is no key, a qualifier the key fixes, a prefix of no composed set or a key its set lacks, qualifiers on a `v:` name, or a version no packaged rule admits. When `DataCatalog` opens: a named set that can answer nothing on the result, such as `fasta_peptides_alpha` before `apb-fasta verify-peptides` runs, `fasta_proteins_alpha` before `apb-fasta merge-annotations` or `obs_annotation_alpha` on a result `apb2 annotate` never annotated; the message says what to run |

## Requirements and `enforce`

A set's requirement rows say how strongly a consumer needs a kind on a level. `enforce` makes them binding, like a log level, and checks them once, when the catalog opens: `DataCatalog` on the levels the result has, `Catalog` on the levels of the rule its version matches.

| Opened with | `required` absent | `recommended` absent | `optional` absent |
| --- | --- | --- | --- |
| no `enforce` | opens | opens | opens |
| `enforce="required"` | raises `MissingRequiredField` | opens, one logged warning | opens |
| `enforce="recommended"` | raises | raises | opens |

- One `MissingRequiredField` lists every missing field, one line each; its `missing` holds each `(resolution, row)` pair
- Each missing field is recorded with its requirement in the set's snapshot, so the [snapshot](#snapshots)'s per-level summary counts it
- Only a field the reviewed software version lacks is missing; a field the catalogue cannot decide stays an `UnresolvedField` at lookup
- A lookup does not enforce: once the catalog is open, `get` returns `None` for an absent field, as without `enforce`
- `enforce` raises `ValueError` when none of the named sets has requirement rows
- [Catalogues](catalogues.md) shows each set's requirements

## Snapshots

`attach_snapshot(parsed, snapshot)` returns a new result holding the snapshot; data is shared, not copied. `ResolutionSnapshot.model_validate(metadata["catalog"][<set>]["result"])` reads it back.

- Stored as JSON at `metadata["catalog"][<set>]["result"]`, beside other sets' snapshots
- Each level's request counts sit at that level's `metadata["catalog"][<set>]["summary"]`
- Both persist in h5ad, h5mu, Parquet and DuckDB
- Self-contained: the set's description, vocabulary (its kinds, and its qualifiers with their values), level bindings, catalogued fields, each with its kind and qualifiers, and every answer
- JSON Schema: `apb_catalog/data/apb-catalog-resolution-0.9.schema.json`, regenerated by `make schema`

## The long table

`catalogue_table(catalogue=None)` returns every set, or one, as one row per entry and software version pattern; `apb-catalog table [SET] [--output PATH]` writes it as CSV.

| Column | Holds |
| --- | --- |
| `set` | The catalogue set |
| `source` | The conversion software, an app such as `apb-fasta`, or `annotation:<convention>` |
| `software_version_pattern` | The version pattern of the software's APB2 rule the row holds for; null for an app's or annotation's entry, which holds for every version |
| `level`, `location`, `table` | Where the field lives; `table` only for `varm` |
| `name` | The APB column, or `prefix:<prefix>` |
| `qualifier.<name>` | One column per qualifier of any set |
| `requirement` | `required`, `recommended` or `optional` where the set requires the field |
| `entry_id` | The entry, `<source>/<version>/<level>/<attribute>/<key>/<column>`; `set`, `entry_id`, `kind` and `software_version_pattern` identify a row |

## Rule check

`catalogues()` returns one row per set: purpose, users, entry count, whether it has requirements. `rule_coverage(set)` checks every packaged rule level against one set, one row per field:

| Column | Holds |
| --- | --- |
| `software`, `version`, `software_version_pattern`, `level` | The packaged rule level: a software version from `versions.csv` and a level its entries name; `version` is the label entries use |
| `kind`, `qualifiers`, `origin` | The meaning; `qualifiers` as `key=value` pairs |
| `producer` | An app such as `apb-fasta`; null for the conversion software's fields, APB2-computed ones included |
| `requirement` | `required`, `recommended` or `optional` where the set has requirements |
| `location`, `table`, `column` | Where the field lives; `column` is null when nothing supplies a required field |
| `needs` | What to run before a plugin set's field exists, such as `apb-fasta verify-peptides` |
| `verdict` | `fail` when a `required` field is missing, `warn` when a `recommended` one is, `pass` otherwise, a missing `optional` field included; null without requirements |

## Command line

| Command | Prints |
| --- | --- |
| `apb-catalog` | Every set with its entry count and purpose |
| `apb-catalog check SET` | `FAIL`, `WARN` or `PASS` per rule level, or `----` for every level of a set without requirements; exits 1 on a `FAIL` |
| `apb-catalog check SET SOFTWARE` | One vendor's rule levels, with every field and its column |
| `apb-catalog meaning SET` | One row per rule level and field; `--software`, `--version` narrow it, `--format csv` |
| `apb-catalog table [SET]` | The long table as CSV; `--output PATH` |
