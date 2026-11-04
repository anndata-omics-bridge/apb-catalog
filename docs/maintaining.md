# Maintaining

The CSV tables under `src/apb_catalog/data/` are the source of truth, one file per table for every set; [Catalogues](catalogues.md) is generated from them.

| File | Holds |
| --- | --- |
| `entries.csv` | One row per catalogued field: its set, its source (the conversion software, with every column its APB2 rule writes; an app such as apb-fasta; or `annotation:<convention>` for sample-annotation fields found by column prefix), the software version patterns it holds for, where it lives, its kind and its evidence |
| `entry_qualifiers.csv` | Each entry's qualifiers besides its kind |
| `vocabulary.csv` | Each set's row with its purpose and users, its qualifiers and their values; every qualifier defines `unknown` |
| `keys.csv` | Each set's keys: the name callers ask by, its kind and its PSI-MS terms |
| `key_qualifiers.csv` | The qualifier values each key fixes besides its kind, one row each, such as `normalization` `run_setting` for `normalized_intensity`; a qualifier without a row stays open |
| `requirements.csv` | Each set's requirement rows by key, if it has any |
| `producers.csv` | Apps whose fields exist only once they have run: the metadata path recording the run, and what to run |
| `versions.csv` | The software versions APB2 has a rule for: the label entries name, and the rule's version pattern a converted result stores; written by `make versions` from APB2's packaged rules |
| `datapackage.json` | Each table's columns and keys, and the catalog version |

A version's levels are the levels its packaged entries name; a set with vendor entries reviews every one. Nothing reads APB2's parse rules at runtime: `make versions` and the tests read them when the catalog is written.

## After an APB2 rule change

A level binds to a catalogue variant by its rule's software name, version pattern and level, so editing a rule within one version keeps its entries. Run `make versions` first; `test_versions_match_apb2s_packaged_rules` fails until then, and `test_the_entries_name_every_level_apb2_converts` until the entries name every level APB2 converts.

| Change | Do |
| --- | --- |
| A catalogued field's meaning changes | Update or remove its entries |
| A field is renamed, dropped or moved between `layers` and `var` | Fix the entries the entries test names; a move changes the id's attribute, key and column |
| New rule version | Add a row with its label for each entry that still holds, in `apb` too; a `*` entry holds already; the coverage report and the apb completeness test list what is missing |
| A version pattern changes | Rewrite it in `versions.csv`; entries name the label |
| Software name changes | Rename the source field of the vendor's entry ids; the load fails until then |
| New vendor | Name APB2's columns for it in `apb`; other sets review it with no entries until they need its fields |
| A new version pattern | Give it a short label in `VERSION_LABELS` in `scripts/versions.py`; entries name that label |

Then run `make docs-tables`.

## An entry

One row in `entries.csv`, and its other qualifiers in `entry_qualifiers.csv`:

```csv
set,entry_id,kind,basis,evidence_url
confidence,DIA-NN/2.x/peptidoform_ion/layers/PEP/-,pep,"DIA-NN README: 'run-specific posterior error probability for the precursor'.",https://github.com/vdemichev/DiaNN#main-output-reference
```

```csv
set,entry_id,kind,qualifier,value
confidence,DIA-NN/2.x/peptidoform_ion/layers/PEP/-,pep,stage,identification
```

| Column | Holds |
| --- | --- |
| `entry_id` | Where the field lives, built as CPE names are: `<source>/<version>/<level>/<attribute>/<key>/<column>`, six fields of one value each. `test_an_entry_id_names_where_its_field_lives` checks the grammar |
| `kind` and `entry_qualifiers.csv` | Every qualifier the set's vocabulary declares; `unknown` where the evidence does not establish one. One id with two kinds, such as a protein column APB2 marks `protein_assignment` and `fasta_accessions`, is two rows; qualifiers join on `entry_id` and `kind` |
| `basis`, `evidence_url` | Why the meaning holds, and where it is stated |

| Id field | Holds |
| --- | --- |
| `source` | The conversion software, an app named in `producers.csv`, or `annotation:<convention>` |
| `version` | One `versions.csv` label (`1.8–1.9`, `2.x`), or `*` for every version, later ones included; an entry holding for several, not all, versions is one row per version |
| `level`, `attribute` | The quantification level, or `*` for every level in an app's or annotation convention's entry, and `obs`, `var`, `layers` or `varm` |
| `key` | A layer's or `varm` table's name; `-` for obs and var |
| `column` | The APB output name of an obs, var or `varm` column, not the vendor column: `Q_Value`, not `Q.Value`; `-` for a layer; a trailing `*` matches obs columns by prefix |

Each entry has exactly one key: the one whose kind and fixed values it carries; the load fails otherwise. `test_a_key_has_at_most_one_vendor_entry_per_rule_level` fails when two fields of one level and location share a key in a vendor set; give each its own kind, as `confidence` does with `library_q_value`, or its own key.

## Adding a set

1. Add its row, purpose and users, and its vocabulary, `kind` and any other qualifiers with `unknown` among their values, to `vocabulary.csv`
2. Add its keys to `keys.csv`: one per kind, or one per kind and value of a qualifier that changes the meaning, with that value in `key_qualifiers.csv`
3. Add its entries to `entries.csv` and their qualifiers to `entry_qualifiers.csv`
4. Add its requirement rows, if any, to `requirements.csv`
5. Catalogue only the fields its consumer reads, or, for a set that qualifies an APB2 role, every field with that role
6. Add a section with its generated-block markers to `docs/catalogues.md`, then run `make docs-tables`

## Plugin sets

An installed package adds a set without changing this one, through the `apb_catalog.catalogues` entry-point group:

```toml
[project.entry-points."apb_catalog.catalogues"]
toy = "toy_package.catalogue"
```

The package's folder holds the same CSV files with the set's rows only, in the columns `datapackage.json` declares; `key_qualifiers.csv`, `requirements.csv` and `producers.csv` are optional.

`DataCatalog`, `catalogues()`, `rule_coverage()` and `apb-catalog check` then work as for a packaged set. A name a packaged set or another plugin already uses raises `ValueError`.

An app that runs after conversion, such as apb-fasta, is named in `producers.csv` with `requires`, the metadata path recording its run joined by `.`, and `instruction`; its entries name it as their source and no version pattern. Until the result records that run, they answer `unknown` with the instruction.

## Checks

| Test | Fails when |
| --- | --- |
| `test_every_packaged_rule_level_is_reviewed` | A set has no variant for a software name, version pattern and level APB2 packages |
| `test_versions_match_apb2s_packaged_rules` | `versions.csv` differs from APB2's packaged rules; run `make versions` |
| `test_the_entries_name_every_level_apb2_converts` | The entries name a level APB2 does not convert, or miss one it does |
| `test_entries_name_fields_the_rules_retain` | An entry names a field the rule of one of its version patterns does not keep |
| `test_packaged_catalogues_load_against_the_vocabulary` | A qualifier is missing or not admitted, a table's columns differ from `datapackage.json`, a key repeats, or an entry names a software or version `versions.csv` does not list |
| `test_every_packaged_set_states_its_purpose_and_users` | `entries.csv` and the set rows of `vocabulary.csv` disagree |
| `test_domain_sets_hold_no_apb2_columns` | A set other than `apb` names an APB2 `ProForma_*` column |
| `test_vendor_flags_answer_only_where_the_rule_reads_the_vendor` | A vendor entry names `apb_Decoy` or `apb_Contaminant` on a rule that reads no vendor input for it |
| `test_abundance_entries_are_the_layers_apb2_marks_abundance` | The `abundance` set and the layers APB2 marks `abundance` differ |
| `test_apb_entries_name_fixed_columns_or_role_columns` | An `apb` entry names neither a fixed column nor the column its rule marks with the role its kind names |
| `test_every_fixed_and_role_column_a_rule_writes_has_an_apb_entry` | A packaged rule level writes a fixed or role column `apb` does not name for that software version |
| `test_every_set_answers_without_apb2s_rule_declarations` | A lookup, the coverage check or the long table reads APB2's parse rules |
| `test_every_entry_has_exactly_one_key` | An entry's kind and qualifiers match no key of its set, or several |
| `test_a_key_has_at_most_one_vendor_entry_per_rule_level` | Two fields of one software version, level and location share a key in a vendor set |
| `test_requirements_must_name_the_sets_keys` | `requirements.csv` names a key the set does not list |
| `test_the_catalogue_page_matches_the_generator` | `docs/catalogues.md` differs from `make docs-tables` |
| `tests/test_bundle.py` | The bundle cannot be built, for example a new version pattern has no `SAMPLE_VERSIONS` entry in `scripts/build_bundle.py` |

| Command | Runs |
| --- | --- |
| `.venv/bin/pytest tests/test_source.py tests/test_catalog.py tests/test_coverage.py tests/test_docs.py` | The catalogue checks but the bundle's, while editing |
| `make docs-tables` | Regenerates the tables of `docs/catalogues.md` |
| `make schema` | Regenerates the snapshot JSON Schema after a snapshot model change |
| `make versions` | Rewrites `versions.csv` from APB2's packaged rules |
| `make bundle` | Builds the language bundle (catalogue tables) and its test bundle (expected answers, synthetic results) into `build/`; a release attaches both and opens the apbCatalogR update pull request |
| `make check` | Format, lint, types, dependencies, tests, build and documentation |
| `apb-catalog check SET` | Every packaged rule level against one set's requirements |
