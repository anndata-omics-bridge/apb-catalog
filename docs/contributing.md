# Contributing

The catalog can be extended to suit your application. New terms are supported by adding catalog entries, without changing APB2's parser, and you are welcome to create catalogs of your own. Together with APB2's tested parsing rules, the catalogs are meant as a community resource on what quantification software reports and how applications use it.

## What a catalog is

A catalogue set covers one topic, such as `abundance` or `confidence`, in four tables:

| Part | Holds | Example |
| --- | --- | --- |
| Vocabulary | The kinds and qualifiers of the topic, each with `unknown` | kind `intensity`, normalization `none` or `run_setting` |
| Keys | The names an application asks by | `intensity`: an intensity without normalization |
| Entries | For each software version, the column that holds a key, with the tool's documentation as evidence | DIA-NN 2.x: `Precursor_Quantity` |
| Requirements | Optional: how strongly an application needs each key, `required`, `recommended` or `optional` | `abundance` recommends `intensity` on ions |

Two people fill a set:

- the application developer names the terms the application needs, and how strongly
- the integrator writes the entries for each software version and quotes the tool's documentation

`apb-catalog check SET` then reports, for every software version APB2 converts, which required or recommended terms it lacks. The [catalog viewer](https://fgcz-ms.uzh.ch/public/apb-catalog/) shows every set in the browser.

## Ways to contribute

| You want | Do |
| --- | --- |
| A software version or a field a set lacks | Add its entries by pull request; see [An entry](maintaining.md#an-entry) |
| An entry corrected | Open an issue or a pull request with the evidence |
| Terms for your application, from Python, R and TypeScript | Add a set to apb-catalog by pull request; see [Adding a set](maintaining.md#adding-a-set) |
| A catalog released with your own application | A plugin set in your package; see below |

## A catalog of your own

A Python package adds a set without changing apb-catalog: the same CSV tables with only its rows, registered as an entry point:

```toml
[project.entry-points."apb_catalog.catalogues"]
toy = "toy_package.catalogue"
```

- `DataCatalog(result, "toy")`, `rule_coverage("toy")` and `apb-catalog check toy` work as for a packaged set
- the set stays yours: you release and version it with your application, and it can be private
- Python only: plugin sets never enter the bundle that apbCatalogR and apb-catalog-ts read; for R and TypeScript, contribute the set to apb-catalog
- [Plugin sets](maintaining.md#plugin-sets) has the details

## Getting started

- See what exists in the [catalog viewer](https://fgcz-ms.uzh.ch/public/apb-catalog/) and on [Catalogues](catalogues.md)
- Open an [issue](https://github.com/anndata-omics-bridge/apb-catalog/issues) naming your application, the terms it needs and how strongly
- A pull request runs `make check`, whose tests compare every entry with APB2's packaged rules
