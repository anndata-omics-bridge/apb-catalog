# Maintaining

## After an APB2 rule change

A changed rule document changes the fingerprint of its effective rules, and the drift test fails with the new fingerprints:

```bash
make test
```

1. Check that the change leaves the catalogued fields' meaning intact; update or remove entries otherwise
2. Replace the variant's `fingerprints` in each affected `src/apb_catalog/data/sources/<set>/<vendor>.json` with the ones the test reports
3. Update the vendor catalogue's `review` date and APB2 revision
4. Bump the APB2 revision pinned in `.github/workflows/quality.yml`, which the full CI job checks out beside this package

Results converted before the change keep the old fingerprint and raise `UnresolvedField` until they are reconverted.

## Adding a consumer

1. Add a directory `src/apb_catalog/data/sources/<set>/` with one catalogue per vendor, listing every packaged rule level
2. Add the set to `CATALOGUES` in `apb_catalog/source.py`
3. Add its concept and kinds to `apb_catalog/data/vocabulary.json`
4. Catalogue only the fields that consumer reads

## Checks

```bash
make check     # format, lint, types, dependencies, tests, build, documentation
make schema    # regenerate the snapshot JSON Schema after changing the snapshot model
```
