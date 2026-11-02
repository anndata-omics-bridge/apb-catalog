# Maintaining

The CSV tables under `src/apb_catalog/data/` are the source of truth, one file per table for every set; [Catalogues](catalogues.md) is generated from them.

| File | Holds |
| --- | --- |
| `entries.csv` | One row per catalogued field: its set, its source (the conversion software, with every column its APB2 rule writes; an app such as apb-fasta; or `annotation:<convention>` for sample-annotation fields found by column prefix), the software version patterns it holds for, where it lives, its kind and its evidence |
| `entry_qualifiers.csv` | Each entry's qualifiers besides its kind |
| `vocabulary.csv` | Each set's row with its purpose and users, its qualifiers and their values; every qualifier defines `unknown` |
| `requirements.csv` | Each set's requirement rows, if it has any |
| `producers.csv` | Apps whose fields exist only once they have run: the metadata path recording the run, and what to run |
| `rule_levels.csv` | The levels APB2 converts for each software version pattern, with the pattern's label; written by `make rule-levels` from APB2's packaged rules |
| `datapackage.json` | Each table's columns and keys, and the catalog version |

A set with vendor entries reviews every rule level of `rule_levels.csv`. Nothing reads APB2's parse rules at runtime: `make rule-levels` and the tests read them when the catalog is written.

## After an APB2 rule change

A level binds to a catalogue variant by its rule's software name, version pattern and level, so editing a rule within one version keeps its entries. Run `make rule-levels` first; `test_rule_levels_match_apb2s_packaged_rules` fails until then.

| Change | Do |
| --- | --- |
| A catalogued field's meaning changes | Update or remove its entries |
| A field is renamed, dropped or moved between `layers` and `var` | Fix the entries the entries test names; a move changes `location` |
| New rule version | Add its version pattern to each entry that still holds, in `apb` too; the coverage report and the apb completeness test list what is missing |
| A version pattern changes | Rewrite it in every entry that names it; the load fails until then |
| Software name changes | Rename the `source` of the vendor's entries; the load fails until then |
| New vendor | Name APB2's columns for it in `apb`; other sets review it with no entries until they need its fields |
| A new version pattern | Give it a short label in `VERSION_LABELS` in `scripts/rule_levels.py` |

Then run `make docs-tables`.

## An entry

One row in `entries.csv`, and its other qualifiers in `entry_qualifiers.csv`:

```csv
set,entry_id,source,software_version_pattern,level,location,table,reference_by,reference,kind,basis,evidence_url
confidence,diann.peptidoform_ion.PEP,DIA-NN,^2\..*,peptidoform_ion,layers,,name,PEP,pep,"DIA-NN README: 'run-specific posterior error probability for the precursor'.",https://github.com/vdemichev/DiaNN#main-output-reference
```

```csv
set,entry_id,qualifier,value
confidence,diann.peptidoform_ion.PEP,stage,identification
```

| Column | Holds |
| --- | --- |
| `software_version_pattern` | The version patterns of the software's APB2 rules the entry holds for, as `rule_levels.csv` and a converted result write them, separated by `;`; empty for an app's or an annotation's entry |
| `reference_by`, `reference` | `name` and the APB output name, not the vendor column: `Q_Value`, not `Q.Value`; or `prefix` and an obs column prefix |
| `table` | The feature-aligned table of a `varm` field |
| `kind` and `entry_qualifiers.csv` | Every qualifier the set's vocabulary declares; `unknown` where the evidence does not establish one |
| `basis`, `evidence_url` | Why the meaning holds, and where it is stated |

A meaning two fields of one level share makes lookups `ambiguous`, and no test catches it: give each field its own kind, as `confidence` does with `library_q_value`.

## Adding a set

1. Add its row, purpose and users, and its vocabulary, `kind` and any other qualifiers with `unknown` among their values, to `vocabulary.csv`
2. Add its entries to `entries.csv` and their qualifiers to `entry_qualifiers.csv`
3. Add its requirement rows, if any, to `requirements.csv`
4. Catalogue only the fields its consumer reads, or, for a set that qualifies an APB2 role, every field with that role
5. Add a section with its generated-block markers to `docs/catalogues.md`, then run `make docs-tables`

## Plugin sets

An installed package adds a set without changing this one, through the `apb_catalog.catalogues` entry-point group:

```toml
[project.entry-points."apb_catalog.catalogues"]
toy = "toy_package.catalogue"
```

The package's folder holds the same CSV files with the set's rows only, in the columns `datapackage.json` declares; `requirements.csv` and `producers.csv` are optional.

`DataCatalog`, `catalogues()`, `rule_coverage()` and `apb-catalog check` then work as for a packaged set. A name a packaged set or another plugin already uses raises `ValueError`.

An app that runs after conversion, such as apb-fasta, is named in `producers.csv` with `requires`, the metadata path recording its run joined by `.`, and `instruction`; its entries name it as their source and no version pattern. Until the result records that run, they answer `unknown` with the instruction.

## Checks

| Test | Fails when |
| --- | --- |
| `test_every_packaged_rule_level_is_reviewed` | A set has no variant for a software name, version pattern and level APB2 packages |
| `test_rule_levels_match_apb2s_packaged_rules` | `rule_levels.csv` differs from APB2's packaged rules; run `make rule-levels` |
| `test_entries_name_fields_the_rules_retain` | An entry names a field the rule of one of its version patterns does not keep |
| `test_packaged_catalogues_load_against_the_vocabulary` | A qualifier is missing or not admitted, a table's columns differ from `datapackage.json`, a key repeats, or an entry names a software, version pattern or level `rule_levels.csv` does not list |
| `test_every_packaged_set_states_its_purpose_and_users` | `entries.csv` and the set rows of `vocabulary.csv` disagree |
| `test_domain_sets_hold_no_apb2_columns` | A set other than `apb` names an APB2 `ProForma_*` column |
| `test_vendor_flags_answer_only_where_the_rule_reads_the_vendor` | A vendor entry names `apb_Decoy` or `apb_Contaminant` on a rule that reads no vendor input for it |
| `test_abundance_entries_are_the_layers_apb2_marks_abundance` | The `abundance` set and the layers APB2 marks `abundance` differ |
| `test_apb_entries_name_fixed_columns_or_role_columns` | An `apb` entry names neither a fixed column nor the column its rule marks with the role its kind names |
| `test_every_fixed_and_role_column_a_rule_writes_has_an_apb_entry` | A packaged rule level writes a fixed or role column `apb` does not name for that software version |
| `test_every_set_answers_without_apb2s_rule_declarations` | A lookup, the coverage check or the long table reads APB2's parse rules |
| `test_requirements_must_name_vocabulary_kinds` | `requirements.csv` names a kind or value the vocabulary does not define |
| `test_the_catalogue_page_matches_the_generator` | `docs/catalogues.md` differs from `make docs-tables` |
| `tests/test_bundle.py` | The bundle cannot be built, for example a new version pattern has no `SAMPLE_VERSIONS` entry in `scripts/build_bundle.py` |

| Command | Runs |
| --- | --- |
| `.venv/bin/pytest tests/test_source.py tests/test_catalog.py tests/test_coverage.py tests/test_docs.py` | The catalogue checks but the bundle's, while editing |
| `make docs-tables` | Regenerates the tables of `docs/catalogues.md` |
| `make schema` | Regenerates the snapshot JSON Schema after a snapshot model change |
| `make rule-levels` | Rewrites `rule_levels.csv` from APB2's packaged rules |
| `make bundle` | Builds the language bundle (catalogue tables) and its test bundle (expected answers, synthetic results) into `build/`; a release attaches both and opens the apbCatalogR update pull request |
| `make check` | Format, lint, types, dependencies, tests, build and documentation |
| `apb-catalog check SET` | Every packaged rule level against one set's requirements |
