# APB Catalog

APB Catalog tells a consumer which field of an [APB2](https://github.com/anndata-omics-bridge/apb2) result carries the meaning it needs, so the consumer never names vendor columns such as MaxQuant's `PEP`, Spectronaut's `EG_PEP` or DIA-NN's `Q_Value`.

```python
from apb_catalog.api import Catalog

catalog = Catalog(parsed, "identification_confidence")
catalog.layer("ion", concept="confidence")              # ('pep', 'q_value')
pep = catalog.layer("ion", concept="confidence", kind="pep")
```

`pep` is the apb2 layer table itself, the same ions × runs as the abundance layer, or `None` when the vendor reports no PEP.

## Catalogues per consumer

A catalogue annotates only what one consumer needs, never every vendor column.

| Set | Used by | Annotates |
| --- | --- | --- |
| `identification_confidence` | apb-aggregate | Per-run and per-feature PEP and q-value, how likely each identification is correct |
| `miape` | MIAPE-AnnData export (draft) | Protein, peptide and peptidoform fields and the `raw` layer of the MIAPE-AnnData 0.4.0 draft |
| `proteobench_entrapment` | apb-proteobench entrapment scoring | Run, library and experiment-wide precursor q-values, each its own kind |

Every set lists every rule APB2 packages, so a vendor without a relevant field answers `None`, while a software version nobody reviewed raises. See [Catalogues](catalogues.md) for every entry.

## Catalogue or column role?

APB2 rules already declare some meanings themselves: each column entry in `rules.json` can carry [semantic roles](https://anndata-omics-bridge.github.io/apb2/rule-based/#semantic-roles) such as `abundance`, `protein_assignment` or `fasta_accessions`, and every result records them in `uns["column_roles"]` and `uns["layer_roles"]`. The [role policy](https://github.com/anndata-omics-bridge/apb2/blob/main/src/apb2/parserV2/vendor_parse_rules/schema/role_policy.json) owns the vocabulary.

Rule of thumb:

- Meaning several tools need, or apb2 itself defines → role in `rules.json`
- Meaning one consumer or an external standard needs → catalogue
- A catalogue copy of a role would be a second source of truth

## How it stays correct

- An entry holds for the software versions it was reviewed against: the `software_name` and `software_version_pattern` each level's stored `rule_json` declares
- Tests fail when APB2 adds a rule version or level, until a reviewer adds its variant; editing a rule within a version keeps its entries
- Lookups never transform values; the consumer reads the layer or column it is handed
- A snapshot of every lookup can be stored in the result, readable without this package

## Pages

- [Get started](getting-started.md): install, look up, use the data, map to MIAPE
- [Catalogues](catalogues.md): every entry of all three sets
- [Python API](api.md): lookups, errors and snapshots
- [Maintaining](maintaining.md): APB2 rule changes, new consumers, a worked catalogue example
