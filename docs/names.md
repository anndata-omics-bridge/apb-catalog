# Names without data

`Catalog` answers from the catalog alone: which field a software version reports for a key, before any result exists. It takes a software name and version instead of a result; its levels have the same slots as `DataCatalog`'s, holding names:

```python
from apb_catalog.api import Catalog

ion = Catalog("DIA-NN", "2.6.0", "abundance_alpha").levels["peptidoform_ion"]
ion.layers["intensity"]            # 'Precursor_Quantity'
apb = Catalog("DIA-NN", "2.6.0", "apb_alpha").levels["peptidoform_ion"]
apb.var[["peptidoform_ion", "protein_assignment"]]  # ('ProForma_ion', 'Protein_Group')
```

`get` returns the name or `None` and takes qualifiers too: `Catalog("DIA-NN", "2.6.0", "chromatography_alpha").levels["peptidoform_ion"].layers.get("retention_time", unit="minute")` is `'RT'`.

| Call | Raises |
| --- | --- |
| `Catalog("DIA-NN", "3.0", "confidence_alpha")` | `ValueError`: no packaged DIA-NN rule admits version `3.0` |
| `ion.layers["intensities"]` | `KeyError`: no key `intensities`; `get` returns `None` |

## Requirements per software version

`apb-catalog check` checks every packaged rule level against a set's requirements: `FAIL` when a `required` field is missing, `WARN` when a `recommended` one is, `PASS` otherwise. It exits 1 on a `FAIL`.

```bash
apb-catalog check abundance_alpha
```

```text
WARN  AlphaDIA 2.x peptidoform_ion: missing intensity recommended
PASS  DIA-NN 1.8–1.9 peptidoform_ion
WARN  FragPipe 22–23 peptidoform_ion: missing intensity recommended
PASS  MaxQuant 1.5, 1.6, 2.x peptidoform_ion
```

- `rule_coverage("abundance_alpha")` returns the same as a Polars table, one row per field, with `requirement` and `verdict`
- `Catalog(..., enforce="required")` raises `MissingRequiredField` when the version's rule lacks a required field, as `DataCatalog` does on a result
