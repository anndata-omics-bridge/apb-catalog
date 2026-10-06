# Maintaining

## After an APB2 rule change

A level binds to a catalogue variant by the `software_name` and `software_version_pattern` its stored rule declares, plus the level. Editing a rule within one version therefore keeps its entries.

1. Check that the change leaves each catalogued field's meaning intact; update or remove entries otherwise
2. Renamed or dropped output field: the entries test names every entry that still refers to it
3. New rule version: add one variant per level to `src/apb_catalog/data/sources/<set>/<vendor>.json` in every set; the coverage test lists the missing ones. Add the rule to the `rules` of each entry whose meaning still holds
4. Changed software name or version pattern: edit the catalogue's `software_name` or the variant's pattern; the variant test reports each mismatch
5. New vendor: add `<vendor>.json` to every set, with `"entries": []` where the set needs nothing from it

## Adding a consumer

1. Add `src/apb_catalog/data/sources/<set>/` with one catalogue per vendor, covering every packaged rule level
2. Add the set's purpose and users to `src/apb_catalog/data/catalogues.json`
3. Add a concept and its qualifiers to `src/apb_catalog/data/vocabulary.json`, only if no existing concept fits
4. Catalogue only the fields that consumer reads
5. List the set on [Catalogues](catalogues.md), in the [home page](index.md) table and in the README

## Worked example

### Catalogue files

`identification_confidence/diann.json`, trimmed to one variant:

```json
{
  "catalogue_id": "diann",
  "catalogue_version": "0.1",
  "software_name": "DIA-NN",
  "variants": [
    {"rule": "diann/v2/rules.json", "level": "ion", "software_version_pattern": "^2\\..*"}
  ],
  "entries": [
    {
      "entry_id": "diann.ion.Q_Value",
      "rules": ["diann/v2/rules.json"],
      "reference": {"level": "ion", "location": "layers", "name": "Q_Value"},
      "concept": "confidence",
      "qualifiers": {"kind": "q_value", "stage": "identification"},
      "evidence": {
        "basis": "DIA-NN README: 'run-specific precursor q-value'.",
        "source": "https://github.com/vdemichev/DiaNN#main-output-reference"
      }
    },
    {
      "entry_id": "diann.ion.PEP",
      "rules": ["diann/v2/rules.json"],
      "reference": {"level": "ion", "location": "layers", "name": "PEP"},
      "concept": "confidence",
      "qualifiers": {"kind": "pep", "stage": "identification"},
      "evidence": {
        "basis": "DIA-NN README: 'run-specific posterior error probability for the precursor'.",
        "source": "https://github.com/vdemichev/DiaNN#main-output-reference"
      }
    }
  ]
}
```

- `variants`: one per rule and level; `software_name` and `software_version_pattern` copied from the rule
- `rules`: the variants an entry holds for
- `reference.name`: the APB output name, not the vendor column: `Q_Value`, not `Q.Value`
- `qualifiers`: every qualifier the concept declares; `unknown` where the reviewer cannot establish one, which makes matching lookups raise
- `evidence`: why the meaning holds, and where it is stated

`identification_confidence/quantms.json` reviews quantms and finds nothing relevant:

```json
{
  "catalogue_id": "quantms",
  "catalogue_version": "0.1",
  "software_name": "quantms",
  "variants": [
    {"rule": "quantms/rules.json", "level": "ion", "software_version_pattern": "^v?1\\..*"}
  ],
  "entries": []
}
```

### Lookups

Three synthetic results with one ion level each, built like `_result` in `tests/test_catalog.py`:

```python
from apb_catalog.api import Catalog

confidence = Catalog(diann_2, "identification_confidence")   # DIA-NN 2.x, layers Q_Value and PEP
confidence.layer("ion", concept="confidence")                # ('pep', 'q_value')
confidence.layer("ion", concept="confidence", kind="pep")    # resolved: the PEP layer table

quantms = Catalog(quantms_1, "identification_confidence")    # quantms 1.x
quantms.layer("ion", concept="confidence", kind="pep")       # missing: None

unreviewed = Catalog(diann_3, "identification_confidence")   # its rule declares DIA-NN ^3\.
unreviewed.layer("ion", concept="confidence", kind="pep")    # unknown: raises UnresolvedField
```

```text
confidence on ion (stage=identification, kind=pep) is unknown: no source catalogue reviewed DIA-NN ^3\. ion
```

Fix: add a variant for the new version.

Suppose `diann.json` also tagged `Lib_Q_Value` as `q_value`. A result retaining both layers then answers `kind="q_value"` with:

```text
confidence on ion (stage=identification, kind=q_value) is ambiguous: 2 entries match: Q_Value, Lib_Q_Value; candidates: Q_Value, Lib_Q_Value
```

No test catches this. Fix: give each field its own kind, as `proteobench_entrapment` does with `library_q_value`.

## Checks

| Test | Fails when |
| --- | --- |
| Coverage: `test_every_packaged_rule_level_is_reviewed` | a set has no variant for a software name, version pattern and level that APB2 packages |
| Variant: `test_variants_name_the_software_and_version_their_rules_declare` | a variant's software name or version pattern differs from its rule's |
| Entries: `test_entries_name_fields_the_rules_retain` | an entry's `reference` names a layer or var column one of its `rules` does not retain |
| Vocabulary: `test_packaged_catalogues_load_against_the_vocabulary` | qualifiers miss one the concept declares or use a value it does not admit; an entry id repeats; an entry names an undeclared variant; two catalogues review one software version |
| Descriptions: `test_every_packaged_set_states_its_purpose_and_users` | a set directory and `catalogues.json` disagree |

The first four live in `tests/test_source.py`, the last in `tests/test_catalog.py`.

```bash
.venv/bin/pytest tests/test_source.py   # catalogue checks alone, while editing
make check     # format, lint, types, dependencies, tests, build, documentation
make schema    # regenerate the snapshot JSON Schema after changing the snapshot model
```

[Catalogues](catalogues.md) and the entry counts in the README are written by hand; no script generates them. Update them with every entry change.
