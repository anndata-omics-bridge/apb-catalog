# Catalogues

A catalogue set annotates the fields one consumer needs, for every rule APB2 packages. The JSON files under `src/apb_catalog/data/sources/<set>/` are the source of truth; this page is generated from them.

## `aggregate`

Identification confidence that apb-aggregate can weight with: per-run PEP and q-value layers, per-feature PEP, and Sage's MS1-peak q-value (stage `quantification`). Scores, protein-level confidence and vendor summaries are deliberately left out.

Concept `confidence`, kinds:

- `pep`: Posterior error probability: the probability that this single identification is wrong; lower is better.
- `q_value`: The smallest false discovery rate at which this identification, or quantified signal, is accepted; lower is better.

| Software | Rules | Level | Location | APB field | Kind |
| --- | --- | --- | --- | --- | --- |
| AlphaDIA | alphadia/v1_12 | ion | layers | `QValue` | `q_value` |
| AlphaDIA | alphadia/v2 | ion | layers | `QValue` | `q_value` |
| AlphaPept | alphapept | ion | layers | `Q_Value` | `q_value` |
| DIA-NN | diann/v1_7, diann/v1_8, diann/v2 | ion | layers | `Q_Value` | `q_value` |
| DIA-NN | diann/v1_8, diann/v2 | ion | layers | `PEP` | `pep` |
| FragPipe | all | — | — | none relevant | — |
| i2MassChroQ | all | — | — | none relevant | — |
| MaxQuant | maxquant | ion | layers | `PEP` | `pep` |
| MaxQuant | maxquant | peptidoform | var | `PEP` | `pep` |
| MaxQuant | maxquant | peptide | var | `PEP` | `pep` |
| MS-Angel | all | — | — | none relevant | — |
| ProteoBench custom | all | — | — | none relevant | — |
| PEAKS | all | — | — | none relevant | — |
| Proline Studio | all | — | — | none relevant | — |
| quantms | all | — | — | none relevant | — |
| Sage | sage | ion | var | `Q_Value` | `q_value` (quantification) |
| Sage | sage | peptidoform | var | `Q_Value` | `q_value` (quantification) |
| Spectronaut | spectronaut/v15, spectronaut, spectronaut/v21 | ion | layers | `EG_PEP` | `pep` |
| Spectronaut | spectronaut/v15, spectronaut, spectronaut/v21 | ion | layers | `EG_Qvalue` | `q_value` |
| WOMBAT-P | all | — | — | none relevant | — |

## `miape`

Draft mapping onto the MIAPE-AnnData Schema 0.4.0 draft of the HUPO-PSI AI Readiness Working Group. MIAPE-AnnData defines protein-group, peptide, peptidoform and site modalities; APB ion levels have no modality, so ion-only results gain MIAPE fields only after aggregation. Fields an exporter computes, such as `detection_rate` or `length`, are not catalogued. MIAPE-AnnData stores no per-feature confidence; it records FDR filtering as a provenance step.

Concept `miape`, kinds and their requirement level:

- `protein_group`: var, MUST: protein-group identifier as semicolon-separated UniProt accessions; on peptide and peptidoform levels the foreign key to the protein modality.
- `gene_name`: var, SHOULD: gene symbol of the protein group.
- `organism`: var, SHOULD: species of the protein group.
- `protein_description`: var, MAY: free-text protein description, typically the UniProt protein name.
- `n_peptides_used`: var, SHOULD: distinct peptide sequences aggregated into the protein group.
- `is_contaminant`: var, SHOULD: whether the protein group comes from a contaminant database.
- `sequence`: var, MUST: bare amino-acid sequence without modifications or charge.
- `peptidoform`: var, MUST: ProForma 2.0 peptidoform, charge-collapsed.
- `is_unique`: var, MUST: whether the peptide or peptidoform maps to exactly one protein group.
- `n_psms`: var, MAY: peptide-spectrum matches aggregated into the row across all samples.
- `raw`: layers, MUST: the unmodified engine-output quantification matrix.

| Software | Rules | Level | Location | APB field | Kind |
| --- | --- | --- | --- | --- | --- |
| AlphaDIA | alphadia/v2 | protein | var | `Protein_Group` | `protein_group` |
| AlphaDIA | alphadia/v2 | protein | layers | `PG_Intensity` | `raw` |
| AlphaPept | all | — | — | none relevant | — |
| DIA-NN | diann/v1_7, diann/v1_8, diann/v2 | protein | var | `Protein_Group` | `protein_group` |
| DIA-NN | diann/v1_7, diann/v1_8, diann/v2 | protein | var | `Genes` | `gene_name` |
| DIA-NN | diann/v1_7 | protein | layers | `PG_Normalised` | `raw` |
| DIA-NN | diann/v1_8, diann/v2 | protein | layers | `PG_MaxLFQ` | `raw` |
| FragPipe | all | — | — | none relevant | — |
| i2MassChroQ | all | — | — | none relevant | — |
| MaxQuant | maxquant | protein | var | `Protein_IDs` | `protein_group` |
| MaxQuant | maxquant | protein | var | `Gene_Names` | `gene_name` |
| MaxQuant | maxquant | protein | var | `Protein_Names` | `protein_description` |
| MaxQuant | maxquant | protein | var | `Razor_Unique_Peptides` | `n_peptides_used` |
| MaxQuant | maxquant | protein | var | `Potential_Contaminant` | `is_contaminant` |
| MaxQuant | maxquant | protein | layers | `Intensity` | `raw` |
| MaxQuant | maxquant | peptide | var | `ProForma_peptide` | `sequence` |
| MaxQuant | maxquant | peptide | var | `Leading_Razor_Protein` | `protein_group` |
| MaxQuant | maxquant | peptide | var | `Unique_Groups` | `is_unique` |
| MaxQuant | maxquant | peptide | layers | `Intensity` | `raw` |
| MaxQuant | maxquant | peptidoform | var | `ProForma_peptide` | `sequence` |
| MaxQuant | maxquant | peptidoform | var | `Proteins` | `protein_group` |
| MaxQuant | maxquant | peptidoform | var | `Unique_Groups` | `is_unique` |
| MaxQuant | maxquant | peptidoform | layers | `Intensity` | `raw` |
| MS-Angel | all | — | — | none relevant | — |
| ProteoBench custom | all | — | — | none relevant | — |
| PEAKS | all | — | — | none relevant | — |
| Proline Studio | all | — | — | none relevant | — |
| quantms | all | — | — | none relevant | — |
| Sage | sage | peptidoform | var | `ProForma_peptidoform` | `peptidoform` |
| Sage | sage | peptidoform | var | `ProForma_peptide` | `sequence` |
| Sage | sage | peptidoform | var | `Proteins` | `protein_group` |
| Sage | sage | peptidoform | layers | `Intensity` | `raw` |
| Spectronaut | spectronaut/v15, spectronaut, spectronaut/v21 | protein | var | `PG_ProteinGroups` | `protein_group` |
| Spectronaut | spectronaut/v15 | protein | var | `PG_Genes` | `gene_name` |
| Spectronaut | spectronaut/v15 | protein | var | `PG_Organisms` | `organism` |
| Spectronaut | spectronaut/v15, spectronaut, spectronaut/v21 | protein | layers | `PG_Quantity` | `raw` |
| WOMBAT-P | wombat | peptidoform | var | `ProForma_peptidoform` | `peptidoform` |
| WOMBAT-P | wombat | peptidoform | var | `ProForma_peptide` | `sequence` |
| WOMBAT-P | wombat | peptidoform | var | `protein_group` | `protein_group` |
| WOMBAT-P | wombat | peptidoform | layers | `Abundance` | `raw` |
