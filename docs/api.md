# Python API

Everything is imported from `apb_catalog.api`. [Get started](getting-started.md) shows each call on real results.

## Catalogs

| Constructor | Answers from |
| --- | --- |
| `DataCatalog(result, *catalogs, enforce=None)` | An apb2 `ParsedLevels` result: the rule each level was converted with; the named sets composed with `apb`, always in |
| `Catalog(software, version, catalog, enforce=None)` | The packaged APB2 rule whose version pattern admits `version`; no data |

| Method | `DataCatalog` returns | `Catalog` returns |
| --- | --- | --- |
| `layer(level, key, **qualifiers)` | apb2 `FinalLayerTable` or `None` | `Reference` or `None` |
| `var(level, key, **qualifiers)` | Polars `Series` or `None` | `Reference` or `None` |
| `obs(level, key, **qualifiers)` | Polars `Series` or `None` | `Reference` or `None` |
| `keys(level, location, **qualifiers)` | keys offered at `"layers"`, `"var"` or `"obs"`; `()` for none | same |
| `fields()` | Polars `DataFrame`: the [long table](#the-long-table)'s columns plus `present`, `constant` | same |
| `levels[name]` | one result level with AnnData's slots, looked up by key; see [Levels](#levels) | — |
| `snapshot(catalog=None)` | `ResolutionSnapshot` of one set's lookups so far; the first set named by default | — |
| `resolve(request)` | `Resolution` of one explicit request, recorded for the snapshot: status `resolved`, `missing`, `ambiguous` or `unknown`, with candidates and reasons; an undecided answer is a status, not an `UnresolvedField` | — |
| `description` | the first set's `purpose` and `used_by` | same |

- A key is one of the set's keys, listed per set in [Catalogues](catalogues.md): a kind with the qualifier values it fixes, such as `normalized_intensity` (kind `intensity`, normalization `run_setting`)
- `**qualifiers` narrow by a qualifier the key leaves open, such as `unit`; `kind`, or a qualifier the key fixes, raises `ValueError`
- A `Reference` has `level`, `location`, `name` and `table`
- `resolve` takes a request naming a level, optionally a location and a key, and the accepted values of each qualifier; `apb_catalog.api` exports neither its type, `FieldRequest`, nor `Resolution`
- `var` also reads feature-aligned `varm` tables, such as apb-fasta's `fasta_validation`, which only plugin sets catalogue
- `fields()` lists a field APB2 left out because it held one value with `present` false and that value as `constant`
- A level answers only for its own entity: `peptidoform_ion` for precursors, `protein` for protein groups
- Composed sets: a key routes to the sets that define it; two sets naming different fields for one key on one level raise `ValueError` when the catalog is built; `keys()` and `fields()` cover every set; `enforce` applies each set's requirements

## Levels

`DataCatalog(result, "abundance", "confidence").levels["protein"]` has AnnData's slots and returns what AnnData returns, with polars in place of pandas:

| Slot | Returns |
| --- | --- |
| `X` | numpy matrix, observations by variables: the level's primary layer |
| `layers[name]` | numpy matrix, observations by variables |
| `var[name]`, `obs[name]` | polars `Series`; `var` also reads `varm` tables |
| `obs_names`, `var_names` | polars `Series` of strings: the key columns, joined by `\|` |
| `layers.keys()`, `var.keys()`, `obs.keys()` | the keys the level offers there, a `set` |

- Lookup follows cf_xarray: a key first, then the level's own name in that slot, else `KeyError`; `UnresolvedField` when the key names several fields or one the catalogue cannot decide
- `keys()` and `in` know keys only; vendor names are read, not listed
- A key may name the primary layer and then answers `X`; `layers` holds the other layers, as in AnnData
- A matrix is built once per level and shared by every later answer

## Answers

| Answer | Means |
| --- | --- |
| a field | Exactly one catalogued field matches |
| `None` | The level is absent, or its software version was reviewed and has no such field |
| `UnresolvedField` | Two fields match equally, an entry leaves a requested qualifier `unknown`, no catalogue reviewed the level's software version, or a plugin set's later producer, such as `apb-fasta verify-peptides`, has not run; names the reason and candidates |
| `ValueError` | A misspelled set, key or qualifier, a qualifier the key fixes, or a version no packaged rule admits |

## Requirements and `enforce`

A set's requirement rows say how strongly a consumer needs a kind on a level. `enforce` makes them binding, like a log level:

| Created with | `MUST` absent | `SHOULD` absent | `MAY` absent |
| --- | --- | --- | --- |
| no `enforce` | `None` | `None` | `None` |
| `enforce="MUST"` | raises `MissingRequiredField` | `None` and a logged warning | `None` |
| `enforce="SHOULD"` | raises | raises | `None` |

- `enforce` on a set without requirement rows raises `ValueError`
- `UnresolvedField` raises whatever `enforce` says
- [Catalogues](catalogues.md) shows each set's requirements

## Snapshots

| Function | Does |
| --- | --- |
| `attach_snapshot(parsed, snapshot)` | Returns a new result holding the snapshot; data is shared, not copied |
| `stored_snapshot(parsed, catalogue)` | Reads a stored snapshot back, or `None` |
| `stale_levels(parsed, snapshot)` | Levels whose software name or version changed since the snapshot |

- Stored as JSON at `metadata["catalog"][<set>]["result"]`, beside other sets' snapshots
- Each level's request counts sit at that level's `metadata["catalog"][<set>]["summary"]`
- Both persist in h5ad, h5mu, Parquet and DuckDB
- Self-contained: the set's description, vocabulary, level bindings, catalogued fields and every answer
- JSON Schema: `apb_catalog/data/apb-catalog-resolution-0.8.schema.json`, regenerated by `make schema`

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
| `requirement` | `MUST`, `SHOULD` or `MAY` where the set requires the field |
| `entry_id` | The entry; `set`, `entry_id` and `software_version_pattern` identify a row |

## Rule check

`catalogues()` returns one row per set: purpose, users, entry count, whether it has requirements. `rule_coverage(set)` checks every packaged rule level against one set, one row per field:

| Column | Holds |
| --- | --- |
| `software`, `version`, `software_version_pattern`, `level` | The packaged rule level from `rule_levels.csv`; `version` is a short reading of its version pattern |
| `kind`, `qualifiers`, `origin` | The meaning; `qualifiers` as `key=value` pairs |
| `producer` | An app such as `apb-fasta`; null for the conversion software's fields, APB2-computed ones included |
| `requirement` | `MUST`, `SHOULD` or `MAY` where the set has requirements |
| `location`, `table`, `column` | Where the field lives; `column` is null when nothing supplies a required field |
| `needs` | What to run before a plugin set's field exists, such as `apb-fasta verify-peptides` |
| `verdict` | `fail` when a `MUST` field is missing, `warn` for `SHOULD` or `MAY`, `pass` otherwise; null without requirements |

## Command line

| Command | Prints |
| --- | --- |
| `apb-catalog` | Every set with its entry count and purpose |
| `apb-catalog check SET` | `FAIL`, `WARN` or `PASS` per rule level, or `----` for every level of a set without requirements; exits 1 on a `FAIL` |
| `apb-catalog check SET SOFTWARE` | One vendor's rule levels, with every field and its column |
| `apb-catalog meaning SET` | One row per rule level and field; `--software`, `--version` narrow it, `--format csv` |
| `apb-catalog table [SET]` | The long table as CSV; `--output PATH` |
