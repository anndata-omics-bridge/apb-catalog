# APB Catalog

APB Catalog finds a field of an [APB2](https://github.com/anndata-omics-bridge/apb2) result by what it means, so a consumer never names vendor columns such as MaxQuant's `PEP`, Spectronaut's `EG_PEP` or DIA-NN's `Q_Value`.

```python
from pathlib import Path

from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

result = read_parsed_levels(Path("diann.h5mu"))   # any APB2 result
pep = DataCatalog(result, "confidence_alpha").levels["peptidoform_ion"].layers.get("pep")
```

`pep` is a numpy matrix, runs × ions as AnnData's layers, or `None` when the vendor reports no PEP; `layers.name("pep")` names the vendor's column.

With pandas, on the MuData or AnnData object APB2 wrote, the same keys return AnnData's own matrices and pandas Series: `from apb_catalog.api_pandas import DataCatalog`, then `DataCatalog(mdata, "confidence_alpha")`; see [pandas](api.md#pandas).

| Page | For |
| --- | --- |
| [Get started](getting-started.md) | Install, look up fields, use the data |
| [Catalogues](catalogues.md) | Every set: its vocabulary, which software has which field |
| [Python API](api.md) | Every call, answer, table and command |
| [Maintaining](maintaining.md) | APB2 rule changes, new sets, the checks |
| [Contributing](contributing.md) | Extend a catalog, or create your own |

## Catalogue or rule role?

APB2 rules can mark a column with a [semantic role](https://anndata-omics-bridge.github.io/apb2/rule-based/#semantic-roles) such as `abundance_alpha` or `protein_assignment`; the [role policy](https://github.com/anndata-omics-bridge/apb2/blob/main/src/apb2/parserV2/vendor_parse_rules/schema/role_policy.json) owns that vocabulary.

| Meaning | Lives in |
| --- | --- |
| Needed by several tools, or defined by APB2 itself | A role in the rule |
| Needed by one consumer or an external standard | A catalogue set |
| More detail about a role, such as an abundance layer's normalization | A catalogue set that qualifies the role; a test keeps the two equal |

## How it stays correct

- An entry holds for the software versions it was reviewed against: the software name and version pattern each level's stored rule declares
- Tests fail when APB2 adds a rule version or level, until a reviewer adds it
- APB2's parse rules are read only when the catalog is written; at runtime it reads its own tables
- Lookups never transform values; the consumer reads the field it is handed
- A snapshot of every lookup can be stored in the result, readable without this package
