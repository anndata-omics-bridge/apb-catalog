# Maintaining

## After an APB2 rule change

A level binds by the `software_name` and `software_version_pattern` its rule declares, plus the level, so editing a rule within a version keeps its entries.

1. Check that the change leaves the catalogued fields' meaning intact; update or remove entries otherwise
2. A new rule version, or a changed name or version pattern, needs its own variant in each `src/apb_catalog/data/sources/<set>/<vendor>.json`; the variant test reports any variant that disagrees with its rule

## Adding a consumer

1. Add a directory `src/apb_catalog/data/sources/<set>/` with one catalogue per vendor, listing every packaged rule level
2. Add the set's purpose and users to `apb_catalog/data/catalogues.json`
3. Add its concept and kinds to `apb_catalog/data/vocabulary.json`
4. Catalogue only the fields that consumer reads

## Checks

```bash
make check     # format, lint, types, dependencies, tests, build, documentation
make schema    # regenerate the snapshot JSON Schema after changing the snapshot model
```
