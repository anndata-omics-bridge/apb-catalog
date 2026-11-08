# A result named by catalog keys

`as_mudata()` turns the MuData or AnnData APB2 wrote into a new MuData that holds only the fields the named catalog sets describe, each under its key. Any set works. `write_h5mu` writes the new object like any MuData, and the source object is left unchanged.

```python
import mudata
from apb_catalog.api_pandas import DataCatalog

mdata = mudata.read_h5mu("diann.h5mu")        # a DIA-NN 1.8 protein level
keyed = DataCatalog(mdata, "abundance_alpha", "confidence_alpha", "apb_alpha").as_mudata()
keyed.write_h5mu("diann_keyed.h5mu")
keyed
```

```text
MuData object with n_obs × n_vars = 2 × 3
  uns:	'catalog'
  1 modality
    protein:	2 × 3
      var:	'library_q_value', 'q_value', 'decoy', 'contaminant', 'protein_assignment', 'fasta_accessions'
      uns:	'catalog'
      layers:	'intensity', 'intensity_norm_settings[aggregation=top_n]', 'intensity_norm_settings[aggregation=maxlfq]', 'q_value'
```

## What the new object holds

- **Sets:** the named ones alone; `apb_alpha` brings the identifiers and the `decoy` and `contaminant` flags only when named
- **Modalities:** one per level that has a catalogued field; `levels["protein"].as_anndata()` converts a single level
- **`layers`, `var`, `obs`:** one entry per catalogued field, named by its key
- **Run and feature names:** the result's own
- **`X`:** empty, since no set says which layer is primary
- **A field two keys name:** written under both; DIA-NN's `Protein_Group` is both `protein_assignment` and `fasta_accessions`
- **A field in `varm`:** becomes a `var` column

## Layers only

The abundance set's keys are all layers, so on its own it gives a MuData of layers; the run and feature names stay as `obs_names` and `var_names`:

```python
DataCatalog(mdata, "abundance_alpha").as_mudata()
```

```text
MuData object with n_obs × n_vars = 2 × 3
  uns:	'catalog'
  1 modality
    protein:	2 × 3
      uns:	'catalog'
      layers:	'intensity', 'intensity_norm_settings[aggregation=top_n]', 'intensity_norm_settings[aggregation=maxlfq]'
```

## One key, two fields

DIA-NN 1.8 reports two protein intensities normalized as the run was set up: `PG_Normalised`, from the top N precursors, and `PG_MaxLFQ`. Both are `intensity_norm_settings`. The qualifier that tells them apart is added to the key, paired with its value:

| Column | DIA-NN's name |
| --- | --- |
| `intensity` | `PG_Quantity` |
| `intensity_norm_settings[aggregation=top_n]` | `PG_Normalised` |
| `intensity_norm_settings[aggregation=maxlfq]` | `PG_MaxLFQ` |
| `q_value` | `PG_Q_Value` |

Two fields that no qualifier tells apart get their own name as well. With an SDRF and `obs_annotation_alpha` named, every factor column is `group`, so the factors `treatment` and `dose` become `group[field=factor_value_treatment]` and `group[field=factor_value_dose]`.

## The record in `uns["catalog"]`

Each column records where it came from:

```python
protein = keyed["protein"]
protein.uns["catalog"]["layers"]["intensity_norm_settings[aggregation=maxlfq]"]
```

```text
{'set': 'abundance_alpha', 'key': 'intensity_norm_settings', 'qualifiers': {'normalization': 'run_setting', 'aggregation': 'maxlfq', 'ms_level': 'ms2'}, 'location': 'layers', 'name': 'PG_MaxLFQ'}
```

- **`layers`, `var`, `obs`:** for each column, its set, key, qualifiers, and the level's own name for the field and where it sat
- **`absent`:** the required and recommended keys the level lacks. Spectronaut 21's ion level reports no unnormalized intensity, so with `abundance_alpha` the record reads `{'layers': {'intensity': 'recommended'}}`
- **`source`:** the level's APB2 record, `uns["apb"]` as the result held it
- **MuData root:** its own `uns["catalog"]` names the sets and holds the result's root record

## From a Parquet or DuckDB result

`as_mudata` starts from the AnnData or MuData APB2 wrote. Write a result in another format to h5mu first:

```python
from pathlib import Path
from apb2.api import read_parsed_levels, write_parsed_levels

write_parsed_levels(read_parsed_levels(Path("diann.parquet")), Path("diann.h5mu"))
```
