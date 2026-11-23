# Writing an exporter

An exporter asks the catalog for each field by meaning and writes it under the target's name, with no export rule. The examples below write a Perseus table with the Polars `DataCatalog`, a prolfquapp, ProteoPy and AlphaPeptTools file with the pandas one, and QFeatures assays in R with apbCatalogR. On a DIA-NN result that `apb2 convert` wrote and `apb2 annotate` annotated, they write the values `apb-export perseus`, `prolfqua`, `proteopy_ion` and `alphapepttools` write; the Perseus table is the same file. Perseus and prolfquapp also match with apb-fasta's columns.

## Perseus

Perseus loads MaxQuant's `proteinGroups.txt`: one row per protein group, a `<quantity> <run>` column per quantity and run, a `#!{Type}` row, and a `#!{C:<name>}` row per sample annotation. A text table needs no AnnData, so this exporter reads the result with APB2 and asks the Polars `DataCatalog`.

```python
from pathlib import Path

import polars as pl
from apb2.api import read_parsed_levels
from apb_catalog.api import DataCatalog

diann = read_parsed_levels(Path("diann.h5mu"))
answering = DataCatalog.answering_sets(diann)  # the sets this result opens
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

# apb-fasta's gene names, once apb-fasta merge-annotations has run
if "fasta_proteins_alpha" in answering:
    fasta = DataCatalog(diann, "fasta_proteins_alpha").levels["protein"]
    genes = fasta.var["fasta_gene_names"].fill_null("")
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

# Sample groups and subjects, once apb2 annotate has run
samples = pl.DataFrame()
if "obs_annotation_alpha" in answering:
    annotation = DataCatalog(diann, "obs_annotation_alpha").levels["protein"]
    samples = annotation.obs[["group"]]
    subject = annotation.obs.get("subject")
    if subject is not None:
        samples = samples.with_columns(subject)

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
answering = DataCatalog.answering_sets(mdata)  # the sets this result opens
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

# apb-fasta's leading protein of each group, once apb-fasta verify-peptides has run
leading = {
    "IDcolumn": "reported_leading_accession",
    "fasta.id": "reported_leading_id",
    "description": "reported_leading_description",
    "gene_name": "reported_leading_gene_name",
    "protein_length": "reported_leading_protein_length",
    "nr_tryptic_peptides": "reported_leading_tryptic_peptides",
}
if "fasta_peptides_alpha" in answering:
    fasta = DataCatalog(mdata, "fasta_peptides_alpha").levels["peptidoform_ion"]
    for name, key in leading.items():
        var[name] = fasta.var[key]

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
if "obs_annotation_alpha" in answering:
    annotation = DataCatalog(mdata, "obs_annotation_alpha").levels["peptidoform_ion"]
    obs = obs.join(pd.concat([annotation.obs[["group"]], annotation.obs.get("subject")], axis=1))
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

## ProteoPy

ProteoPy's main input is peptides: one `.h5ad`, samples by features, with `sample_id` in `obs` and `peptide_id` and `protein_id` in `var`. `check_proteodata` accepts it as peptide level when every feature names one protein. From DIA-NN that is the precursor level, as `proteopy.read.diann(..., aggr_level="Precursor.Id")` reads it.

```python
import anndata
import mudata
import pandas as pd
from apb_catalog.api_pandas import DataCatalog

mdata = mudata.read_h5mu("diann.h5mu")
answering = DataCatalog.answering_sets(mdata)  # the sets this result opens
ion = DataCatalog(mdata, "apb_alpha").levels["peptidoform_ion"]
runs = list(ion.obs_names)

# One feature per precursor; a precursor naming several proteins is left out
accessions = ion.var["fasta_accessions"].astype("string").str.strip().fillna("")
single = ((accessions != "") & ~accessions.str.contains(";", regex=False)).to_numpy()
var = pd.DataFrame({"peptide_id": ion.var["peptidoform_ion"], "protein_id": accessions})
decoy = ion.var.get("decoy")
if decoy is not None:
    var["decoy"] = decoy.astype(bool)

# apb-fasta's protein annotation, once apb-fasta merge-annotations has run
if "fasta_proteins_alpha" in answering:
    fasta = DataCatalog(mdata, "fasta_proteins_alpha").levels["peptidoform_ion"]
    annotation_fields = {
        "in_fasta": "any_member_in_fasta",
        "gene_id": "fasta_gene_names",
        "description": "fasta_descriptions",
        "fasta_organisms": "fasta_organism_names",
    }
    for column, term in annotation_fields.items():
        values = fasta.var.get(term)
        if values is not None:
            var[column] = values

# Samples, and their groups and subjects once apb2 annotate has run
obs = pd.DataFrame({"sample_id": runs}, index=runs)
if "obs_annotation_alpha" in answering:
    annotation = DataCatalog(mdata, "obs_annotation_alpha").levels["peptidoform_ion"]
    obs = obs.join(pd.concat([annotation.obs[["group"]], annotation.obs.get("subject")], axis=1))

var = var[single]
adata = anndata.AnnData(
    X=ion.X[:, single], obs=obs, var=var.set_index(var["peptide_id"].to_numpy())
)
adata.write_h5ad("proteopy_ion.h5ad")
```

- **One protein per feature:** `fasta_accessions` is the precursor's protein list as the software reports it; ProteoPy's own DIA-NN reader also leaves out precursors naming several proteins
- **Protein level:** the same on `levels["protein"]`, with `protein_id` from `protein_assignment`
- **Rollup:** precursors to peptides is ProteoPy's step, not the exporter's

## AlphaPeptTools

AlphaPeptTools reads one `.h5mu` with a `precursors`, a `peptides` and a `proteins` modality: runs by features, the intensity as `X`, `raw_name` in `obs`, identifiers in `var`. A level the result lacks gets no modality; DIA-NN reports no peptide level.

```python
import anndata
import mudata
import pandas as pd
from apb_catalog.api_pandas import DataCatalog

mdata = mudata.read_h5mu("diann.h5mu")
answering = DataCatalog.answering_sets(mdata)  # the sets this result opens
catalog = DataCatalog(mdata, "apb_alpha")
fasta = None
if "fasta_peptides_alpha" in answering:  # once apb-fasta verify-peptides has run
    fasta = DataCatalog(mdata, "fasta_peptides_alpha")
annotated = "obs_annotation_alpha" in answering  # once apb2 annotate has run

# modality: (level, feature key, its identifier columns and the keys answering them)
modalities = {
    "precursors": (
        "peptidoform_ion",
        "precursor_id",
        {"precursor_id": "peptidoform_ion", "sequence": "peptide", "proteins": "protein_assignment"},
    ),
    "peptides": ("peptide", "sequence", {"sequence": "peptide", "proteins": "protein_assignment"}),
    "proteins": ("protein", "proteins", {"proteins": "protein_assignment"}),
}
peptide_fields = {
    "in_fasta": "peptide_in_fasta",
    "fasta_proteins": "fasta_matching_protein_ids",
    "fasta_organisms": "fasta_matching_organisms",
}


def modality(name: str, key: str, columns: dict[str, str]) -> anndata.AnnData:
    """One level as AlphaPeptTools reads it."""
    level = catalog.levels[name]
    var = pd.DataFrame({column: level.var.get(term) for column, term in columns.items()})
    var = var.dropna(axis="columns", how="all")
    if name != "protein":
        # apb2's vendor marking, joined with apb-fasta's FASTA match where it has run
        contaminant = level.var["contaminant"].astype(bool)
        if fasta is not None:
            verified = fasta.levels[name].var
            matched = verified.get("fasta_matches_contaminant")
            if matched is not None:
                contaminant |= matched.astype(bool)
            for column, term in peptide_fields.items():
                values = verified.get(term)
                if values is not None:
                    var[column] = values
        var["contaminant"] = contaminant
    runs = list(level.obs_names)
    obs = pd.DataFrame({"raw_name": runs}, index=runs)
    if annotated:
        annotation = DataCatalog(mdata, "obs_annotation_alpha").levels[name]
        obs = obs.join(pd.concat([annotation.obs[["group"]], annotation.obs.get("subject")], axis=1))
    return anndata.AnnData(X=level.X, obs=obs, var=var.set_index(var[key].to_numpy()))


out = mudata.MuData(
    {
        modality_name: modality(name, key, columns)
        for modality_name, (name, key, columns) in modalities.items()
        if name in catalog.levels
    }
)
out.write("alphapepttools.h5mu")
sorted(out.mod)   # ['precursors', 'proteins']
```

- **Levels:** `name in catalog.levels` asks whether the result has a level; the peptide modality appears for software that reports peptides, such as MaxQuant
- **Contaminants:** apb2's vendor marking, joined with apb-fasta's FASTA match

## QFeatures

QFeatures is a Bioconductor package, so this exporter asks [apbCatalogR](https://anndata-omics-bridge.github.io/apbCatalogR/), the catalog in R, with the same keys. apbCatalogR reads `.h5ad`, Parquet and DuckDB results, so it opens the Parquet one (`apb2 convert --format parquet`). Each level becomes an assay with the columns `apb-export qfeatures` writes; QFeatures links precursors to proteins by `proteins` and aggregates them.

```r
library(apbCatalogR)
library(QFeatures)

result <- read_parsed_levels("diann.parquet")
answering <- DataCatalog$answering_sets(result)  # the sets this result opens
catalog <- DataCatalog$new(result, "apb_alpha")
fasta <- NULL
if ("fasta_peptides_alpha" %in% answering) {  # once apb-fasta verify-peptides has run
    fasta <- DataCatalog$new(result, "fasta_peptides_alpha")
}

# assay: its level and identifier columns, each with the key answering it
assays <- list(
    precursors = list("peptidoform_ion", c(
        precursor_id = "peptidoform_ion", sequence = "peptide", proteins = "protein_assignment"
    )),
    peptides = list("peptide", c(sequence = "peptide", proteins = "protein_assignment")),
    proteins = list("protein", c(proteins = "protein_assignment"))
)
peptide_fields <- c(
    in_fasta = "peptide_in_fasta",
    fasta_proteins = "fasta_matching_protein_ids",
    fasta_organisms = "fasta_matching_organisms"
)

as_assay <- function(name, columns) {
    level <- catalog$levels[[name]]
    features <- Filter(Negate(is.null), lapply(columns, level$var$get))
    if (name != "protein") {
        # apb2's vendor marking, joined with apb-fasta's FASTA match where it has run
        contaminant <- as.logical(level$var[["contaminant"]])
        if (!is.null(fasta)) {
            verified <- fasta$levels[[name]]$var
            matched <- verified$get("fasta_matches_contaminant")
            if (!is.null(matched)) contaminant <- contaminant | as.logical(matched)
            features <- c(features, Filter(Negate(is.null), lapply(peptide_fields, verified$get)))
        }
        features$contaminant <- contaminant
    }
    features <- as.data.frame(features)
    values <- t(as.matrix(level$X))  # SummarizedExperiment holds features x runs
    dimnames(values) <- list(features[[1]], level$obs_names)
    SummarizedExperiment(assays = list(intensity = values), rowData = features)
}

present <- Filter(function(assay) assay[[1]] %in% names(catalog$levels), assays)
qf <- QFeatures(lapply(present, function(assay) as_assay(assay[[1]], assay[[2]])))

# Groups and subjects, once apb2 annotate has run
if ("obs_annotation_alpha" %in% answering) {
    annotation <- DataCatalog$new(result, "obs_annotation_alpha")$levels$peptidoform_ion
    groups <- annotation$obs[c("group")]
    subject <- annotation$obs$get("subject")
    if (!is.null(subject)) groups$subject <- subject
    colData(qf) <- DataFrame(groups, row.names = annotation$obs_names)
}

qf <- addAssayLink(qf, from = "precursors", to = "proteins",
                   varFrom = "proteins", varTo = "proteins")
qf <- aggregateFeatures(qf, "precursors", fcol = "proteins", name = "aggregated",
                        fun = colSums, na.rm = TRUE)
```

- **Same lookups as Python:** `level$var$get(key)` is `level.var.get(key)`, `NULL` where Python returns `None`; `DataCatalog$answering_sets(result)` lists the sets a result opens
- **Features by runs:** AnnData holds runs by features, SummarizedExperiment features by runs, hence `t()`
- **Not in the page test:** the test runs Python blocks only; this block was run on both results with apbCatalogR 0.99.5 and QFeatures 1.22.0

## Sets an app fills

`fasta_peptides_alpha`, `fasta_proteins_alpha` and `obs_annotation_alpha` answer only once `apb-fasta verify-peptides`, `apb-fasta merge-annotations` or `apb2 annotate` has run on the result; before that, `DataCatalog` raises `ValueError` when it opens, naming what to run. `DataCatalog.answering_sets(result)` lists the sets a result opens without raising, so each exporter above asks it first and leaves out the columns an app that has not run would give.
