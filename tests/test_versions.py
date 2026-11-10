"""The catalog reads APB2's parse rules only when it is written; ``versions.csv`` is the trace."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import NoReturn

import polars as pl
import pytest
from apb2.api import JsonValue, ParsedLevel, ParsedLevels
from scripts.versions import TABLE, render

from apb_catalog import rules
from apb_catalog.api import Catalog, DataCatalog, catalogue_table, rule_coverage
from apb_catalog.source import packaged_catalogues, packaged_descriptions
from tests.packaged_rules import declared_rule_json

SOURCE = Path(__file__).resolve().parents[1] / "src" / "apb_catalog"


def test_versions_match_apb2s_packaged_rules() -> None:
    """Rewrite the table with ``make versions`` after an APB2 rule change."""
    assert render() == TABLE.read_text("utf-8"), "versions.csv is stale; run `make versions`"


def test_the_datapackage_describes_the_versions() -> None:
    """Other readers check the table's columns against ``datapackage.json``."""
    text = resources.files("apb_catalog").joinpath("data", "datapackage.json").read_text("utf-8")
    described = next(
        resource for resource in json.loads(text)["resources"] if resource["name"] == "versions"
    )
    assert tuple(field["name"] for field in described["schema"]["fields"]) == rules.COLUMNS


def test_no_module_reads_apb2s_rule_declarations() -> None:
    """Only the build scripts and the tests read APB2's parse rules."""
    readers = [
        path.name
        for path in SOURCE.rglob("*.py")
        if "packaged_rule_declarations" in path.read_text("utf-8")
    ]
    assert readers == []


def _result() -> ParsedLevels:
    level = ParsedLevel.build(
        pl.DataFrame({"Run": ["R1", "R2"]}),
        ("Run",),
        pl.DataFrame({"ProForma_ion": ["A/2", "B/2"], "Protein_Group": ["P1", "P2"]}),
        ("ProForma_ion",),
        {},
        primary_layer="Precursor_Quantity",
        abundance={"Precursor_Quantity": pl.DataFrame({"c0": [1.0, 2.0], "c1": [3.0, 4.0]})},
        uns={
            "provenance": {
                "rule_json": declared_rule_json("diann/v2/rules.json", "peptidoform_ion")
            }
        },
    )
    # Both apb-fasta steps have run and a sample table is attached, so every packaged set can
    # answer.
    metadata: dict[str, JsonValue] = {
        "fasta": {"provenance": {"peptide_verification": {}, "protein_annotation": {}}},
        "sdrf": {},
    }
    return ParsedLevels(levels={"peptidoform_ion": level}, uns={}, metadata=metadata)


def test_every_set_answers_without_apb2s_rule_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lookups with and without data, the coverage check and the long table read none."""
    result = _result()

    def unavailable() -> NoReturn:
        raise AssertionError("a lookup read APB2's rule declarations")

    monkeypatch.setattr("apb2.api.packaged_rule_declarations", unavailable)
    packaged_catalogues.cache_clear()
    rules.rule_levels.cache_clear()
    rules.versions.cache_clear()
    for name in packaged_descriptions():
        assert not catalogue_table(name).is_empty()
        assert not rule_coverage(name).is_empty()
        named = Catalog("DIA-NN", "2.6.0", name).fields()
        # Without data, only a vendor catalogue names fields: an app's wait for its run and an
        # annotation's bind to a result's columns.
        assert not named.is_empty() or not packaged_catalogues(name).needs_review, name
        DataCatalog(result, name).fields()
    found = DataCatalog(result, "apb_alpha").levels["peptidoform_ion"].var.get("protein_assignment")
    assert found is not None and found.to_list() == ["P1", "P2"]
