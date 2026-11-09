# Maintaining

The CSV tables under `src/apb_catalog/data/` are the source of truth, one file per table for every set; [Catalogues](catalogues.md) is generated from them.

| File | Holds |
| --- | --- |
| `sets.csv` | One row per set: its prefix, which asks the set alone as `c:q_value`, what its fields are, what its kinds name, its purpose and its users |
| `terms.csv` | The root of a set: its terms, each a key at one location (`protein/layers`, or `*/obs` for every level), with the kind it stands for, the qualifier values it fixes (one row per fixed value, or one row with neither), its PSI-MS terms, a definition, and how strongly consumers need it. A term may exist before any row of `catalog.csv` maps it; loading logs a warning for it |
| `kinds.csv` | Each set's kinds: what an entry or a key stands for. A kind is always known; a field whose meaning the reviewer could not establish is not catalogued. A set declared in `sets.csv` alone is being planned and loads without kinds |
| `qualifiers.csv` | Each set's qualifiers, which refine a kind, such as `normalization` or `unit`; never `kind` |
| `qualifier_values.csv` | The values each qualifier admits, `unknown` among them once it admits any |
| `catalog.csv` | One row per mapping of a term to a field and per qualifier: its set, its source (the conversion software, with every column its APB2 rule writes; an app such as apb-fasta; or `annotation:<convention>` for sample-annotation fields found by column prefix), the software version patterns it holds for, where it lives, the term's key with its kind, PSI-MS terms and whether it fixes the qualifier value, repeated from `terms.csv` so each row reads alone, its qualifier and value, and its evidence; a field has one row per qualifier of its set |
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
| New rule version | Add a row with its label for each entry that still holds, in `apb_alpha` too; a `*` entry holds already; the coverage report and the apb completeness test list what is missing |
| A version pattern changes | Rewrite it in `versions.csv`; entries name the label |
| Software name changes | Rename the source field of the vendor's entry ids; the load fails until then |
| New vendor | Name APB2's columns for it in `apb_alpha`; other sets review it with no entries until they need its fields |
| A new version pattern | Give it a short label in `VERSION_LABELS` in `scripts/versions.py`; entries name that label |

Then run `make docs-tables`.

## An entry

One row in `catalog.csv`:

```csv
set,software,location,name,key,kind,qualifier,value,fixed,psi_ms,basis,evidence_url
confidence,DIA-NN/2.x,peptidoform_ion/layers,PEP/-,pep,pep,stage,identification,true,,"DIA-NN README: 'run-specific posterior error probability for the precursor'.",https://github.com/vdemichev/DiaNN#main-output-reference
```

| Column | Holds |
| --- | --- |
| `software`, `location`, `name` | Where the field lives, built as CPE names are, two fields each: `<source>/<version>`, `<level>/<attribute>`, `<key>/<column>`; joined by `/` they are the entry id. `test_an_entry_id_names_where_its_field_lives` checks the grammar |
| `key`, `kind`, `psi_ms` | The key of a term `terms.csv` defines at this location, and the kind and PSI-MS terms that term states. One field with two meanings, such as a protein column APB2 marks `protein_assignment` and `fasta_accessions`, is two rows, one per key |
| `qualifier`, `value` | The entry's value of one qualifier of the set, always as a pair, one row per qualifier: an abundance field has a `normalization`, an `aggregation` and an `ms_level` row; both empty in a set without qualifiers; `unknown` where the evidence does not establish one |
| `fixed` | `true` where the term fixes that qualifier's value in `terms.csv`, as `intensity` fixes normalization `none` and `intensity_ms1` ms_level `ms1`, and the row carries that value; `false` where the key leaves the qualifier open, and on a row without a qualifier |
| `basis`, `evidence_url` | Why the meaning holds, and where it is stated; the same on every row of the field |

| Id part | Holds |
| --- | --- |
| `source` | The conversion software, an app named in `producers.csv`, or `annotation:<convention>` |
| `version` | One `versions.csv` label (`1.8–1.9`, `2.x`), or `*` for every version, later ones included; an entry holding for several, not all, versions is one row per version |
| `level`, `attribute` | The quantification level, or `*` for every level in an app's or annotation convention's entry, and `obs`, `var`, `layers` or `varm` |
| `key` | A layer's or `varm` table's name; `-` for obs and var |
| `column` | The APB output name of an obs, var or `varm` column, not the vendor column: `Q_Value`, not `Q.Value`; `-` for a layer; a trailing `*` matches obs columns by prefix |

The load fails when a key's terms differ in kind or PSI-MS terms or fix different values at two locations, when a term has two requirements, when a `catalog.csv` row maps a term `terms.csv` does not define at its location or differs from its key in kind, PSI-MS terms or `fixed`, when a field's rows differ in basis or evidence, or when an entry does not carry its key's kind and fixed values (another key may describe it too). A term no row maps loads, with a warning. `test_fields_sharing_a_key_on_a_rule_level_differ_in_a_qualifier` fails when two fields of one level and location share a key and every qualifier value in a vendor set; give each its own kind, as `confidence_alpha` does with `library_q_value`, its own key, or a qualifier value that tells them apart.

## Adding a set

1. Add its row, with a prefix no other set has (lowercase, not `v`), its definition, what its kinds name, its purpose and its users, to `sets.csv`; its kinds to `kinds.csv`; and any qualifiers to `qualifiers.csv`, with their values, `unknown` among them, in `qualifier_values.csv`
2. Add its terms to `terms.csv`, before any software maps them: each key at every location it may appear at, with its kind, the qualifier values it fixes, and its requirement where consumers need it; one key per kind, or one per kind and value of a qualifier that changes the meaning
3. Add its entries to `catalog.csv`, each mapping a term at its location, its value marked `fixed` where the term fixes it
4. Catalogue only the fields its consumer reads, or, for a set that qualifies an APB2 role, every field with that role
5. Add a section with its generated-block markers to `docs/catalogues.md`, then run `make docs-tables`

## Plugin sets

An installed package adds a set without changing this one, through the `apb_catalog.catalogues` entry-point group:

```toml
[project.entry-points."apb_catalog.catalogues"]
toy = "toy_package.catalogue"
```

The package's folder holds the same CSV files with the set's rows only, in the columns `datapackage.json` declares; `qualifiers.csv` and `qualifier_values.csv` for a set without qualifiers, and `producers.csv`, are optional.

`DataCatalog`, `catalogues()`, `rule_coverage()` and `apb-catalog check` then work as for a packaged set. A name a packaged set or another plugin already uses raises `ValueError`.

An app that runs after conversion, such as apb-fasta, is named in `producers.csv` with `requires`, the metadata path recording its run joined by `.`, and `instruction`; its entries name it as their source and no version pattern. Until the result records that run, a set of the app's entries alone, such as `fasta_peptides_alpha`, raises `ValueError` with the instruction when `DataCatalog` opens; in a set with vendor entries too, and in `Catalog`, the app's entries answer `unknown` with the instruction. An app whose commands record separate runs, as apb-fasta's `verify-peptides` and `merge-annotations` do, gets one set per command, each with its own `producers.csv` row.

## Checks

| Test | Fails when |
| --- | --- |
| `test_every_packaged_rule_level_is_reviewed` | A set has no variant for a software name, version pattern and level APB2 packages |
| `test_versions_match_apb2s_packaged_rules` | `versions.csv` differs from APB2's packaged rules; run `make versions` |
| `test_the_entries_name_every_level_apb2_converts` | The entries name a level APB2 does not convert, or miss one it does |
| `test_entries_name_fields_the_rules_retain` | An entry names a field the rule of one of its version patterns does not keep |
| `test_packaged_catalogues_load_against_the_vocabulary` | A qualifier is missing or not admitted, a table's columns differ from `datapackage.json`, a key repeats, or an entry names a software or version `versions.csv` does not list |
| `test_every_packaged_set_states_its_purpose_and_users` | `catalog.csv` and `sets.csv` disagree |
| `test_a_plugin_set_has_a_prefix_of_its_own` | A set's prefix is `v`, is not lowercase letters, digits and `_`, or is another set's |
| `test_domain_sets_hold_no_apb2_columns` | A set other than `apb_alpha` names an APB2 `ProForma_*` column |
| `test_vendor_flags_answer_only_where_the_rule_reads_the_vendor` | A vendor entry names `apb_Decoy` or `apb_Contaminant` on a rule that reads no vendor input for it |
| `test_abundance_entries_are_the_layers_apb2_marks_abundance` | The `abundance_alpha` set and the layers APB2 marks `abundance_alpha` differ |
| `test_apb_entries_name_fixed_columns_or_role_columns` | An `apb_alpha` entry names neither a fixed column nor the column its rule marks with the role its kind names |
| `test_every_fixed_and_role_column_a_rule_writes_has_an_apb_entry` | A packaged rule level writes a fixed or role column `apb_alpha` does not name for that software version |
| `test_every_set_answers_without_apb2s_rule_declarations` | A lookup, the coverage check or the long table reads APB2's parse rules |
| `test_every_entry_is_described_by_its_key` | An entry does not carry the kind and fixed values of the key it names |
| `test_fields_sharing_a_key_on_a_rule_level_differ_in_a_qualifier` | Two fields of one software version, level and location share a key and every qualifier value in a vendor set |
| `test_requirements_must_name_the_sets_keys` | A requirement names a key the set does not list |
| `test_a_term_exists_before_any_row_maps_it` | A term no `catalog.csv` row maps fails to load, logs no warning, or loses its requirement |
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
