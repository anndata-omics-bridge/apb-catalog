"""The synthetic results the documentation's examples run on: a DIA-NN 1.8.1 report converted
and annotated by APB2, and the same result as apb-fasta leaves it. No real data."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import polars as pl
from apb2.api import (
    AnnotationCompiler,
    JsonValue,
    ParsedLevel,
    ParsedLevels,
    ParseRuleCompiler,
    write_parsed_levels,
)

RUNS = ("run_A1", "run_A2", "run_B1", "run_B2")
# Modified sequence and protein group: a fixed modification, a UniProt "db|ACC|NAME" member,
# a contaminant and a two-member group.
PRECURSORS = (
    ("PEPTIDEK", "P1"),
    ("AAC(UniMod:4)LLK", "sp|P2|P2_HUMAN"),
    ("YEASTPEPK", "P3"),
    ("CONTPEPK", "Cont_P4"),
    ("SHAREDK", "P5;CON__P6"),
    ("LASTPEPK", "P7"),
)
COLUMNS = (
    "Run",
    "Modified.Sequence",
    "Stripped.Sequence",
    "Precursor.Charge",
    "Precursor.Id",
    "Protein.Group",
    "Protein.Ids",
    "Protein.Names",
    "Genes",
    "Precursor.Quantity",
    "Precursor.Normalised",
    "Q.Value",
    "Global.Q.Value",
    "Lib.Q.Value",
    "PEP",
    "RT",
    "PG.Quantity",
    "PG.Normalised",
    "PG.MaxLFQ",
    "PG.Q.Value",
    "Lib.PG.Q.Value",
    "Global.PG.Q.Value",
)


def _row(run_index: int, index: int) -> tuple[object, ...]:
    modified, group = PRECURSORS[index]
    run, number, scale = RUNS[run_index], index + 1, run_index + 1
    return (
        run,
        modified,
        modified.replace("(UniMod:4)", ""),
        2,
        f"{modified}2",
        group,
        group,
        group,
        f"G{number}",
        1000.0 * number * scale,
        900.0 * number * scale,
        0.001 * number * scale,
        0.002 * number,
        0.0005 * number,
        0.01 * number * scale,
        10.0 + index + run_index / 10,
        2000.0 * number * scale,
        1800.0 * number * scale,
        500.0 * number,
        0.0001 * number * scale,
        0.0002 * number,
        0.001 * number,
    )


def _write_diann(folder: Path) -> tuple[Path, Path]:
    """A DIA-NN 1.8.1 report and log; one precursor in five is absent from a run."""
    rows = ["\t".join(COLUMNS)]
    for run_index in range(len(RUNS)):
        for index in range(len(PRECURSORS)):
            if (run_index + index) % 5 != 4:
                rows.append("\t".join(str(value) for value in _row(run_index, index)))
    report = folder / "report.tsv"
    report.write_text("\n".join(rows) + "\n", encoding="utf-8")
    log = folder / "report.log.txt"
    log.write_text("DIA-NN 1.8.1 (Data-Independent Acquisition by Neural Networks)\n", "utf-8")
    return report, log


def _write_design(folder: Path) -> Path:
    """A prolfquapp-style sample table: each run's group and biological replicate."""
    path = folder / "design.tsv"
    lines = ["raw_file\tgroup\tBioReplicate", *(f"{run}\t{run[4]}\t{run[4:]}" for run in RUNS)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def diann_result(folder: Path) -> ParsedLevels:
    """The report's precursor and protein levels, annotated with the sample table."""
    report, log = _write_diann(folder)
    levels = ("peptidoform_ion", "protein")
    parsed = ParseRuleCompiler.detect(report, log, levels).compile().parse()
    return AnnotationCompiler().compile(_write_design(folder)).parse(parsed).annotate().parsed


def _leading(group: str) -> str | None:
    """The accession of a group's leading protein, or ``None`` for one the FASTA lacks."""
    member = group.split(";")[0]
    accession = member.split("|")[1] if "|" in member else member
    return None if accession.startswith("Cont_") else accession


def _verified_ion(level: ParsedLevel) -> ParsedLevel:
    leading = [_leading(group) for group in level.var.frame.get_column("Protein_Group")]
    table = pl.DataFrame(
        {
            "reported_leading_accession": leading,
            "reported_leading_id": [f"sp|{a}|{a}_HUMAN" if a else None for a in leading],
            "reported_leading_description": [f"Protein {a}" if a else None for a in leading],
            "reported_leading_gene_name": [f"GENE_{a}" if a else None for a in leading],
            "reported_leading_protein_length": [300 if a else None for a in leading],
            "reported_leading_tryptic_peptides": [12 if a else None for a in leading],
        }
    )
    return replace(level, varm={**level.varm, "fasta_validation": table})


def _annotated_protein(level: ParsedLevel) -> ParsedLevel:
    leading = [_leading(group) for group in level.var.frame.get_column("Protein_Group")]
    table = pl.DataFrame({"fasta_gene_names": [f"GENE_{a}" if a else None for a in leading]})
    return replace(level, varm={**level.varm, "fasta": table})


def with_fasta(parsed: ParsedLevels) -> ParsedLevels:
    """The result as apb-fasta leaves it: its tables in ``varm`` and its run recorded."""
    levels = dict(parsed.levels)
    levels["peptidoform_ion"] = _verified_ion(levels["peptidoform_ion"])
    levels["protein"] = _annotated_protein(levels["protein"])
    ran: dict[str, JsonValue] = {
        "fasta": {"provenance": {"peptide_verification": {}, "protein_annotation": {}}}
    }
    return replace(parsed, levels=levels, metadata={**parsed.metadata, **ran})


def write_results(folder: Path) -> dict[str, Path]:
    """Each variant's folder, holding ``diann.h5mu`` and ``diann.parquet``."""
    parsed = diann_result(folder)
    variants = {"plain": parsed, "fasta": with_fasta(parsed)}
    folders: dict[str, Path] = {}
    for name, result in variants.items():
        target = folder / name
        target.mkdir()
        write_parsed_levels(result, target / "diann.h5mu")
        write_parsed_levels(result, target / "diann.parquet")
        folders[name] = target
    return folders
