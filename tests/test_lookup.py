"""Stage 2: names without data, enforced requirements, stale fields, roles, prefixes, the table."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, cast

import polars as pl
import pytest
from apb2.api import JsonValue, ParsedLevel, ParsedLevels

from apb_catalog.catalog import (
    METADATA_KEY,
    Catalog,
    DataCatalog,
    MissingRequiredField,
    Reference,
    StaleField,
    attach_snapshot,
)
from apb_catalog.table import KEY_COLUMNS, catalogue_table
from tests.packaged_rules import declared_rule_json


def _result(
    rule: str,
    layers: Sequence[str],
    var: Mapping[str, Sequence[object]] | None = None,
    *,
    obs: Mapping[str, Sequence[str]] | None = None,
    roles: Mapping[str, str] | None = None,
    rule_json: str | None = None,
    uns: Mapping[str, JsonValue] | None = None,
    metadata: dict[str, JsonValue] | None = None,
) -> ParsedLevels:
    """One peptidoform-ion level of three runs and two features, stored as ``rule`` declares."""
    runs = pl.DataFrame({"Run": ["R1", "R2", "R3"], **{k: list(v) for k, v in (obs or {}).items()}})
    features = pl.DataFrame(
        {"ProForma_ion": ["A/2", "B/2"], **{k: list(v) for k, v in (var or {}).items()}}
    )
    values = {
        name: pl.DataFrame({f"c{run}": [float(offset + run)] * 2 for run in range(3)})
        for offset, name in enumerate(layers)
    }
    stored: dict[str, JsonValue] = {
        "provenance": {"rule_json": rule_json or declared_rule_json(rule, "peptidoform_ion")},
        **(uns or {}),
    }
    level = ParsedLevel.build(
        runs,
        ("Run",),
        features,
        ("ProForma_ion",),
        roles or {},
        primary_layer=layers[0],
        abundance=values,
        uns=stored,
    )
    return ParsedLevels(levels={"peptidoform_ion": level}, uns={}, metadata=metadata or {})


def test_catalog_answers_names_from_software_and_version() -> None:
    """The packaged rule whose version pattern admits the version decides the columns."""
    abundance = Catalog("DIA-NN", "2.6.0", "abundance")
    assert abundance.layer("peptidoform_ion", kind="intensity", normalization="none") == Reference(
        level="peptidoform_ion", location="layers", name="Precursor_Quantity"
    )
    assert abundance.kinds("peptidoform_ion", "layers") == ("intensity", "ms1_intensity")
    older = Catalog("DIA-NN", "1.8.1", "confidence")
    assert older.var("peptidoform_ion", kind="library_q_value") == Reference(
        level="peptidoform_ion", location="var", name="Lib_Q_Value"
    )
    with pytest.raises(ValueError, match=r"no packaged DIA-NN rule admits version '9.0'"):
        Catalog("DIA-NN", "9.0", "abundance")


def test_catalog_names_roles_and_fixed_columns_of_the_apb_set() -> None:
    """A role answers with the column the version's rule marks; a fixed name is that name."""
    apb = Catalog("DIA-NN", "2.6.0", "apb")
    assert apb.var("peptidoform_ion", kind="protein_assignment") == Reference(
        level="peptidoform_ion", location="var", name="Protein_Group"
    )
    assert apb.var("peptidoform_ion", kind="peptidoform_ion") == Reference(
        level="peptidoform_ion", location="var", name="ProForma_ion"
    )
    assert apb.var("protein", kind="peptide") is None
    fields = apb.fields()
    assert fields.get_column("present").all()
    assert "concept" not in fields.columns


def test_data_catalog_finds_the_role_column_of_the_result() -> None:
    """The role names whichever column the result's own rule marked."""
    parsed = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised"],
        {"Protein_Group": ["P1", "P2"]},
        roles={"protein_assignment": "Protein_Group"},
    )
    found = DataCatalog(parsed, "apb").var("peptidoform_ion", kind="protein_assignment")
    assert found is not None and found.to_list() == ["P1", "P2"]


def test_an_annotation_column_is_found_by_its_convention_prefix() -> None:
    """A prolfquapp table's ``group`` column is the condition, its ``subject`` the replicate."""
    obs = {"group_condition": ["A", "A", "B"], "subject": ["s1", "s2", "s1"]}
    annotated = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised"],
        obs=obs,
        metadata={"prolfquapp": {"schema_version": "4"}},
    )
    catalog = DataCatalog(annotated, "apb")
    condition = catalog.obs("peptidoform_ion", kind="condition")
    assert condition is not None and condition.to_list() == ["A", "A", "B"]
    replicate = catalog.obs("peptidoform_ion", kind="bioreplicate")
    assert replicate is not None and replicate.to_list() == ["s1", "s2", "s1"]
    plain = DataCatalog(_result("diann/v2/rules.json", ["Precursor_Normalised"], obs=obs), "apb")
    assert plain.obs("peptidoform_ion", kind="condition") is None, "no convention recorded"


def test_enforce_must_warns_for_a_missing_should_field(caplog: pytest.LogCaptureFixture) -> None:
    """PEAKS has no un-normalized intensity: a warning, a summary entry, and no exception."""
    parsed = _result("peaks/rules.json", ["Normalized_Area"])
    catalog = DataCatalog(parsed, "abundance", enforce="MUST")
    with caplog.at_level(logging.WARNING, logger="apb_catalog"):
        found = catalog.layer("peptidoform_ion", kind="intensity", normalization="none")
    assert found is None
    assert "SHOULD field kind=intensity, normalization=none on peptidoform_ion" in caplog.text
    attached = attach_snapshot(parsed, catalog.snapshot())
    records = cast(dict[str, Any], attached.levels["peptidoform_ion"].metadata[METADATA_KEY])
    summary = {entry["name"]: entry for entry in records["abundance"]["summary"]}
    assert (
        summary["missing_required_requests"]["value"],
        summary["missing_required_requests"]["status"],
    ) == (
        1,
        "attention",
    )


def test_enforce_should_raises_for_a_missing_should_field() -> None:
    """``enforce="SHOULD"`` makes SHOULD fields binding too."""
    catalog = DataCatalog(
        _result("peaks/rules.json", ["Normalized_Area"]), "abundance", enforce="SHOULD"
    )
    with pytest.raises(MissingRequiredField, match="SHOULD field"):
        catalog.layer("peptidoform_ion", kind="intensity", normalization="none")


def test_enforce_raises_for_a_missing_must_field() -> None:
    """A peptidoform-ion level without ``ProForma_peptide`` misses a MUST field of the apb set."""
    catalog = DataCatalog(
        _result("diann/v2/rules.json", ["Precursor_Normalised"]), "apb", enforce="MUST"
    )
    with pytest.raises(MissingRequiredField, match="MUST field kind=peptide"):
        catalog.var("peptidoform_ion", kind="peptide")
    assert (
        DataCatalog(_result("diann/v2/rules.json", ["Precursor_Normalised"]), "apb").var(
            "peptidoform_ion", kind="peptide"
        )
        is None
    ), "without enforce, absence is None"


def test_enforce_needs_requirements() -> None:
    """A set without requirement rows has nothing to enforce."""
    with pytest.raises(ValueError, match="sets no requirements"):
        DataCatalog(_result("peaks/rules.json", ["Normalized_Area"]), "confidence", enforce="MUST")


def _edited_rule(edit: str) -> str:
    rule = json.loads(declared_rule_json("maxquant_wide/rules.json", "peptidoform_ion"))
    layers = rule["measurements"]["layers"]
    pep = next(layer for layer in layers if layer["name"] == "PEP")
    if edit == "source":
        pep["source"] = "Some other column"
    elif edit == "drop":
        layers.remove(pep)
    else:
        pep["note"] = "an edited note"
    return json.dumps(rule)


def test_a_field_declared_differently_is_stale() -> None:
    """The stored rule read PEP from another column than the current rule: reconvert."""
    parsed = _result(
        "maxquant_wide/rules.json", ["Intensity", "PEP"], rule_json=_edited_rule("source")
    )
    with pytest.raises(
        StaleField,
        match=r'PEP: this result reads "Some other column", the current rule "evidence.PEP"; reconvert',
    ):
        DataCatalog(parsed, "confidence").layer("peptidoform_ion", kind="pep")


def test_a_field_the_stored_rule_lacks_is_stale() -> None:
    """The current rule declares PEP; the result's rule did not."""
    parsed = _result(
        "maxquant_wide/rules.json", ["Intensity", "PEP"], rule_json=_edited_rule("drop")
    )
    with pytest.raises(StaleField, match="this result reads no such field"):
        DataCatalog(parsed, "confidence").layer("peptidoform_ion", kind="pep")


def test_a_changed_note_is_not_stale() -> None:
    """Only the field's declaration counts, without its note."""
    parsed = _result(
        "maxquant_wide/rules.json", ["Intensity", "PEP"], rule_json=_edited_rule("note")
    )
    found = DataCatalog(parsed, "confidence").layer("peptidoform_ion", kind="pep")
    assert found is parsed.levels["peptidoform_ion"].layers["PEP"]


def test_fields_lists_absent_fields_with_their_constant() -> None:
    """DIA-NN's PEP held one value, so APB2 left it out; ``fields`` says which."""
    uninformative: dict[str, JsonValue] = {
        "uninformative_fields": {
            "single_valued": {"obs": {}, "var": {}, "layers": {"PEP": {"value": 0.0}}},
            "effectively_empty": {"obs": {}, "var": {}, "layers": {}},
        }
    }
    parsed = _result(
        "diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"], uns={"result": uninformative}
    )
    fields = DataCatalog(parsed, "confidence").fields()
    pep = fields.filter(pl.col("name") == "PEP")
    assert pep.select("present", "constant").rows() == [(False, "0.0")]
    assert fields.filter(pl.col("name") == "Q_Value").get_column("present").to_list() == [True]


def test_the_long_table_lists_every_set() -> None:
    """One row per entry and rule, the qualifiers as columns, and no concept."""
    table = catalogue_table()
    assert table.columns[: len(KEY_COLUMNS)] == list(KEY_COLUMNS)
    assert table.columns[-2:] == ["requirement", "entry_id"]
    assert "concept" not in table.columns
    assert set(table.get_column("set")) == {
        "abundance",
        "confidence",
        "proteobench_entrapment",
        "apb",
    }
    library = table.filter(
        (pl.col("set") == "confidence") & (pl.col("qualifier.kind") == "library_q_value")
    )
    assert {"Lib_Q_Value", "EG_LibraryQvalue"} <= set(library.get_column("name"))
    duplicated = table.group_by("set", "entry_id", "rule").len().filter(pl.col("len") > 1)
    assert duplicated.is_empty(), "set, entry id and rule identify a row"
