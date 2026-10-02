# Catalogues

A catalogue set annotates fields of one kind of meaning, for every rule APB2 packages; `data/catalogues.json` states each set's purpose and users, and `Catalog.description` returns it. The JSON files under `src/apb_catalog/data/sources/<set>/` are the source of truth; this page is generated from them.

## `identification_confidence`

How likely each identification, or the signal quantified for it, is correct; used by apb-aggregate for confidence-weighted rollups: per-run PEP and q-value layers, per-feature PEP, and Sage's MS1-peak q-value (stage `quantification`). Scores, protein-level confidence and vendor summaries are deliberately left out.

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

## `proteobench_entrapment`

The precursor q-values ProteoBench's entrapment scoring ranks by; used by apb-proteobench's `EntrapmentAnalyzer` and `run entrapment`. Each q-value is its own kind, so the scorer can score every one a result offers. Only the vendors ProteoBench's entrapment module accepts carry entries.

Concept `confidence`, kinds:

- `q_value`: The smallest false discovery rate at which this identification, or quantified signal, is accepted; lower is better.
- `library_q_value`: The q-value of the identification's spectral-library entry, built across all runs; lower is better.
- `global_q_value`: The q-value of the identification across the whole experiment; lower is better.

| Software | Rules | Level | Location | APB field | Kind |
| --- | --- | --- | --- | --- | --- |
| AlphaDIA | alphadia/v1_12 | ion | layers | `QValue` | `q_value` |
| AlphaDIA | alphadia/v2 | ion | layers | `QValue` | `q_value` |
| DIA-NN | diann/v1_7, diann/v1_8, diann/v2 | ion | layers | `Q_Value` | `q_value` |
| DIA-NN | diann/v1_7, diann/v1_8, diann/v2 | ion | layers | `Lib_Q_Value` | `library_q_value` |
| DIA-NN | diann/v1_7, diann/v1_8, diann/v2 | ion | layers | `Global_Q_Value` | `global_q_value` |
| Spectronaut | spectronaut/v15, spectronaut, spectronaut/v21 | ion | layers | `EG_Qvalue` | `q_value` |
| Spectronaut | spectronaut/v21 | ion | layers | `EG_LibraryQvalue` | `library_q_value` |
| Every other vendor | all | — | — | none relevant | — |
