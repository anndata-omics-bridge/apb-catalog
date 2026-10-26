# APB Catalog

APB Catalog finds a field of an [APB2](https://github.com/anndata-omics-bridge/apb2) result by what it means, so a consumer never names vendor columns such as MaxQuant's `PEP`, Spectronaut's `EG_PEP` or DIA-NN's `Q_Value`.

```python
from apb_catalog.api import DataCatalog

pep = DataCatalog(result, "confidence").layer("peptidoform_ion", kind="pep")
```

`pep` is the apb2 layer table itself, the same ions × runs as the abundance layer, or `None` when the vendor reports no PEP.

| Page | For |
| --- | --- |
| [Get started](getting-started.md) | Install, look up fields, use the data |
| [Catalogues](catalogues.md) | Every set: its vocabulary, which software has which field |
| [Python API](api.md) | Every call, answer, table and command |
| [Maintaining](maintaining.md) | APB2 rule changes, new sets, the checks |

## Catalogue or rule role?

APB2 rules can mark a column with a [semantic role](https://anndata-omics-bridge.github.io/apb2/rule-based/#semantic-roles) such as `abundance` or `protein_assignment`; the [role policy](https://github.com/anndata-omics-bridge/apb2/blob/main/src/apb2/parserV2/vendor_parse_rules/schema/role_policy.json) owns that vocabulary.

| Meaning | Lives in |
| --- | --- |
| Needed by several tools, or defined by APB2 itself | A role in the rule |
| Needed by one consumer or an external standard | A catalogue set |
| More detail about a role, such as an abundance layer's normalization | A catalogue set that qualifies the role; a test keeps the two equal |

## How it stays correct

- An entry holds for the software versions it was reviewed against: the software name and version pattern each level's stored rule declares
- Tests fail when APB2 adds a rule version or level, until a reviewer adds it
- Lookups never transform values; the consumer reads the field it is handed
- A snapshot of every lookup can be stored in the result, readable without this package
