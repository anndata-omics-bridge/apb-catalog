# Maintaining

The JSON under `src/apb_catalog/data/` is the source of truth; [Catalogues](catalogues.md) is generated from it.

| Folder or file | Holds |
| --- | --- |
| `sources/<set>/<vendor>.json` | One catalogue per vendor: its rule variants and entries |
| `producers/<set>/<producer>.json` | Fields APB writes itself, such as APB2's `ProForma_*` columns |
| `annotations/<set>/<convention>.json` | Sample-annotation fields of the `sdrf` or `prolfquapp` convention, found by column prefix |
| `vocabulary.json` | Each set's qualifiers and their values |
| `requirements.json` | Each set's requirement rows, if it has any |
| `catalogues.json` | Each set's purpose and users |

## After an APB2 rule change

A level binds to a catalogue variant by its rule's software name, version pattern and level, so editing a rule within one version keeps its entries.

| Change | Do |
| --- | --- |
| A catalogued field's meaning changes | Update or remove its entries |
| A field is renamed, dropped or moved between `layers` and `var` | Fix the entries the entries test names; a move changes `location` |
| New rule version | Add one variant per level to `<vendor>.json` in every set, and the rule to each entry that still holds; the coverage test lists what is missing |
| Software name or version pattern changes | Edit `software_name` or the variant's pattern; the variant test reports each mismatch |
| New vendor | Add `<vendor>.json` to every set, with `"entries": []` where the set needs nothing |
| A new version pattern | Give it a short label in `VERSION_LABELS` in `src/apb_catalog/coverage.py` |

Then run `make docs-tables`.

## An entry

```json
{
  "entry_id": "diann.peptidoform_ion.PEP",
  "rules": ["diann/v2/rules.json"],
  "reference": {"level": "peptidoform_ion", "location": "layers", "name": "PEP"},
  "qualifiers": {"kind": "pep", "stage": "identification"},
  "evidence": {
    "basis": "DIA-NN README: 'run-specific posterior error probability for the precursor'.",
    "source": "https://github.com/vdemichev/DiaNN#main-output-reference"
  }
}
```

| Key | Holds |
| --- | --- |
| `rules` | The rule variants the entry holds for |
| `reference.name` | The APB output name, not the vendor column: `Q_Value`, not `Q.Value` |
| `qualifiers` | Every qualifier the set's vocabulary declares; `unknown` where the evidence does not establish one |
| `evidence` | Why the meaning holds, and where it is stated |

A meaning two fields of one level share makes lookups `ambiguous`, and no test catches it: give each field its own kind, as `confidence` does with `library_q_value`.

## Adding a set

1. Add `sources/<set>/` with one catalogue per vendor, covering every packaged rule level
2. Add its purpose and users to `catalogues.json`
3. Add its vocabulary, `kind` and any other qualifiers, to `vocabulary.json`
4. Catalogue only the fields its consumer reads, or, for a set that qualifies an APB2 role, every field with that role
5. Add a section with its generated-block markers to `docs/catalogues.md`, then run `make docs-tables`

## Plugin sets

An installed package adds a set without changing this one, through the `apb_catalog.catalogues` entry-point group:

```toml
[project.entry-points."apb_catalog.catalogues"]
toy = "toy_package.catalogue"
```

| The package's folder holds | As |
| --- | --- |
| `catalogue.json` | The set's `purpose` and `used_by` |
| `vocabulary.json` | `{"definition": ..., "qualifiers": {"kind": ..., ...}}` |
| `requirements.json`, optional | Rows `{"level", "location", "kind", "qualifiers", "requirement"}` |
| `sources/<vendor>.json` | One catalogue per vendor, as for a packaged set |
| `producers/<producer>.json`, optional | Fields APB writes itself |
| `annotations/<convention>.json`, optional | Sample-annotation fields |

`DataCatalog`, `catalogues()`, `rule_coverage()` and `apb-catalog check` then work as for a packaged set. A name a packaged set or another plugin already uses raises `ValueError`.

A producer that runs after conversion, such as apb-fasta, declares `requires`, the metadata path recording its run, and `instruction`; until the result records that run, its entries answer `unknown` with the instruction.

## Checks

| Test | Fails when |
| --- | --- |
| `test_every_packaged_rule_level_is_reviewed` | A set has no variant for a software name, version pattern and level APB2 packages |
| `test_variants_name_the_software_and_version_their_rules_declare` | A variant's software name or version pattern differs from its rule's |
| `test_entries_name_fields_the_rules_retain` | An entry names a field one of its rules does not keep |
| `test_packaged_catalogues_load_against_the_vocabulary` | A qualifier is missing or not admitted, an entry id repeats, an entry names an undeclared variant, or two catalogues review one version |
| `test_every_packaged_set_states_its_purpose_and_users` | A set folder and `catalogues.json` disagree |
| `test_vendor_files_hold_no_apb2_columns` | A vendor file names an APB2 `ProForma_*` column |
| `test_vendor_flags_answer_only_where_the_rule_reads_the_vendor` | A vendor entry names `apb_Decoy` or `apb_Contaminant` on a rule that reads no vendor input for it |
| `test_abundance_entries_are_the_layers_apb2_marks_abundance` | The `abundance` set and the layers APB2 marks `abundance` differ |
| `test_apb2_entries_name_fixed_columns_or_var_roles` | An APB2 producer entry names neither a fixed column nor a var role |
| `test_requirements_must_name_vocabulary_kinds` | `requirements.json` names a kind or value the vocabulary does not define |
| `test_the_catalogue_page_matches_the_generator` | `docs/catalogues.md` differs from `make docs-tables` |
| `tests/test_bundle.py` | The bundle cannot be built, for example a new version pattern has no `SAMPLE_VERSIONS` entry in `scripts/build_bundle.py` |

| Command | Runs |
| --- | --- |
| `.venv/bin/pytest tests/test_source.py` | The catalogue checks alone, while editing |
| `make docs-tables` | Regenerates the tables of `docs/catalogues.md` |
| `make schema` | Regenerates the snapshot JSON Schema after a snapshot model change |
| `make bundle` | Builds the language bundle into `build/`; a release attaches it and opens the apbCatalogR update pull request |
| `make check` | Format, lint, types, dependencies, tests, build and documentation |
| `apb-catalog check SET` | Every packaged rule level against one set's requirements |
