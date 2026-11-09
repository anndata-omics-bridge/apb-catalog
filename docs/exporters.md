# Writing an exporter

An exporter asks the catalog for each field by meaning and writes it under the target's name. The two examples below write a Perseus table with the Polars `DataCatalog` and a prolfquapp `.h5ad` with the pandas one, no export rule. On a DIA-NN result that `apb2 convert` wrote and `apb2 annotate` annotated, with or without apb-fasta, they write the values `apb-export perseus` and `apb-export prolfqua` write; the Perseus table is the same file.

## Perseus

Perseus loads MaxQuant's `proteinGroups.txt`: one row per protein group, a `<quantity> <run>` column per quantity and run, a `#!{Type}` row, and a `#!{C:<name>}` row per sample annotation. A text table needs no AnnData, so this exporter reads the result with APB2 and asks the Polars `DataCatalog`.

```python
from pathlib import Path

import polars as pl
from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

diann = read_parsed_levels(Path("diann.h5mu"))
protein = DataCatalog(diann, "abundance_alpha", "confidence_alpha", "apb_alpha").levels["protein"]
runs = protein.obs_names.to_list()

# Feature columns and their Perseus types: T text, N number, C categorical; a flag is "+"
flags = ["Reverse", "Potential contaminant"]
table = pl.DataFrame(
    {
        "Protein IDs": protein.var["protein_assignment"],
        "Q-value": protein.var.get("q_value"),
        "Reverse": protein.var["decoy"],
        "Potential contaminant": protein.var["contaminant"],
    }
).with_columns(
    pl.when(pl.col(flag)).then(pl.lit("+")).otherwise(pl.lit("")).alias(flag) for flag in flags
)
types = ["T", "N", "C", "C"]

# apb-fasta's gene names, once apb-fasta has run; its protein table has no catalog key
fasta = diann.levels["protein"].varm.get("fasta")
if fasta is not None:
    genes = fasta.get_column("fasta_gene_names").cast(pl.String).fill_null("")
    table = table.insert_column(1, genes.alias("Gene names"))
    types.insert(1, "T")

# A "<quantity> <run>" column per quantity the result reports and run; a 0 is missing
quantities = {
    "Intensity": protein.layers.get("intensity"),
    "LFQ intensity": protein.layers.get("intensity_norm_settings", aggregation="maxlfq"),
    "iBAQ": protein.layers.get("ibaq"),
}
column_runs = []
for name, values in quantities.items():
    if values is None:
        continue
    for position, (run, row) in enumerate(zip(runs, values)):
        table = table.with_columns(pl.Series(f"{name} {run}", row).replace(0, None))
        types.append("E")
        column_runs.append(position)

# Sample groups and subjects, none for a result apb2 annotate never annotated
try:
    annotation = DataCatalog(diann, "obs_annotation_alpha").levels["protein"]
    samples = annotation.obs[["group"]]
    subject = annotation.obs.get("subject")
    if subject is not None:
        samples = samples.with_columns(subject)
except ValueError:
    samples = pl.DataFrame()

with open("perseus.txt", "w", encoding="utf-8") as out:
    out.write("\t".join(table.columns) + "\n")
    out.write("#!{Type}" + "\t".join(types) + "\n")
    blank = [""] * (len(types) - len(column_runs))
    for values in samples.iter_columns():
        cells = blank + [str(values[position]) for position in column_runs]
        out.write(f"#!{{C:{values.name}}}" + "\t".join(cells) + "\n")
    table.write_csv(
        out, separator="\t", include_header=False, null_value="NaN", quote_style="never"
    )
```

- **Quantities by meaning:** `aggregation="maxlfq"` picks DIA-NN's `PG_MaxLFQ` or MaxQuant's `LFQ intensity`; a quantity the software does not report is `None` and gets no columns
- **`get` and `[...]`:** `get` for a field the target can do without; `[...]` raises `KeyError` for one it cannot
- **Annotation:** `group` holds every grouping column, one per SDRF factor; `subject` the biological replicate

## prolfquapp

prolfquapp reads one `.h5ad`: precursors by runs, the intensity as `X`, q-values and PEP as layers, protein, peptide and precursor identifiers in `var`, and its configuration in `uns`. It writes AnnData, so it asks the pandas `DataCatalog`, whose answers are AnnData's own values.

```python
import anndata
import mudata
import numpy as np
import pandas as pd
from apb_catalog.api_pandas import DataCatalog

mdata = mudata.read_h5mu("diann.h5mu")
catalog = DataCatalog(mdata, "abundance_alpha", "confidence_alpha", "apb_alpha")
ion, protein = catalog.levels["peptidoform_ion"], catalog.levels["protein"]
runs = list(ion.obs_names)

# One row per precursor, named protein~peptide~precursor
proteins = ion.var["protein_assignment"]
peptides = ion.var["peptide"]
precursors = ion.var["peptidoform_ion"]
var = pd.DataFrame(
    {
        "feature_id": proteins + "~" + peptides + "~" + precursors,
        "protein_Id": proteins,
        "IDcolumn": proteins,
        "fasta.id": proteins,
        "description": proteins,
        "peptide_Id": peptides,
        "precursor_Id": precursors,
        "nr_children": 1,
    }
)

# apb-fasta's leading protein of each group, once apb-fasta has run
leading = {
    "IDcolumn": "reported_leading_accession",
    "fasta.id": "reported_leading_id",
    "description": "reported_leading_description",
    "gene_name": "reported_leading_gene_name",
    "protein_length": "reported_leading_protein_length",
    "nr_tryptic_peptides": "reported_leading_tryptic_peptides",
}
try:
    fasta = DataCatalog(mdata, "apb_fasta_alpha").levels["peptidoform_ion"]
    for name, key in leading.items():
        var[name] = fasta.var[key]
except ValueError:
    pass

group_of = pd.Index(protein.var["protein_assignment"])


def per_precursor(values: np.ndarray | None) -> np.ndarray | None:
    """Protein-group values, runs × groups, read for each precursor through its group."""
    if values is None:
        return None
    return pd.DataFrame(values, columns=group_of).reindex(columns=proteins).to_numpy()


intensity = ion.layers.get("intensity")
if intensity is None:
    intensity = ion.X
experiment = protein.var.get("library_q_value")
if experiment is None:
    experiment = protein.var["q_value"]
layers = {
    "qValue": ion.layers.get("q_value"),
    "pg_qValue": per_precursor(protein.layers.get("q_value")),
    "pg_qValue_experiment": per_precursor(np.tile(experiment, (len(runs), 1))),
    "pep": ion.layers.get("pep"),
}
layers = {name: values for name, values in layers.items() if values is not None}

# Runs, and their groups and subjects once apb2 annotate has run
obs = pd.DataFrame({"sampleName": runs, "raw.file": runs}, index=runs)
try:
    annotation = DataCatalog(mdata, "obs_annotation_alpha").levels["peptidoform_ion"]
    obs = obs.join(pd.concat([annotation.obs[["group"]], annotation.obs.get("subject")], axis=1))
except ValueError:
    pass
factors = [name for name in obs.columns if name not in ("sampleName", "raw.file")]

hierarchy = ["protein_Id", "peptide_Id", "precursor_Id"]
adata = anndata.AnnData(
    X=intensity,
    obs=obs,
    var=var.set_index(var["feature_id"].to_numpy()),
    layers=layers,
    uns={
        "X_layer_name": "intensity",
        "prolfquapp": {
            "artifact_type": "lfqdata",
            "schema_version": "1.0.0",
            "layer_names": ["intensity", *layers],
            "protein_annotation": {
                "pID": "protein_Id",
                "full_id": "protein_Id",
                "description": "description",
                "cleaned_ids": "IDcolumn",
                "exp_nr_children": "nrPeptides",
                "pattern_contaminants": "^zz|^CON|Cont_",
                "pattern_decoys": "^REV_|^rev",
            },
            "analysis_configuration": {
                "sep": "~",
                "file_name": "raw.file",
                "sample_name": "sampleName",
                "isotope_label": "isotopeLabel",
                "ident_q_value": "qValue",
                "nr_children": "nr_children",
                "work_intensity": ["intensity"],
                "is_response_transformed": False,
                "factor_depth": 1,
                "hierarchy": {key: [key] for key in hierarchy},
                "hierarchy_keys": hierarchy,
                "hierarchy_depth": 1,
                "min_peptides_protein": 2,
                "factors": {name: name for name in factors},
            },
        },
    },
)
adata.write_h5ad("prolfqua.h5ad")
```

- **Protein-group fields:** `per_precursor` reads a protein-level matrix for each precursor through its `protein_assignment`; a precursor whose group the protein level lacks gets NaN
- **Fallbacks:** plain `if … is None`; the experiment-wide protein q-value is the library one where the result has it, else the global one
- **Left out:** the software name in `uns`, which the catalog does not answer, and ProteoBench's entrapment q-value

## Sets an app fills

`apb_fasta_alpha` and `obs_annotation_alpha` answer only once apb-fasta or `apb2 annotate` has run; before that, `DataCatalog` raises `ValueError` when it opens. Each exporter above opens them on their own and skips the columns they give when they raise.
