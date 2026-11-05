"""Stage 2: names without data, enforced requirements, role columns, prefixes, the table."""

from __future__ import annotations

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
    attach_snapshot,
)
from apb_catalog.resolver import UnresolvedField
from apb_catalog.table import KEY_COLUMNS, catalogue_table
from tests.packaged_rules import declared_rule_json


def _result(
    rule: str,
    layers: Sequence[str],
    var: Mapping[str, Sequence[object]] | None = None,
    *,
    obs: Mapping[str, Sequence[str]] | None = None,
    roles: Mapping[str, str] | None = None,
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
        "provenance": {"rule_json": declared_rule_json(rule, "peptidoform_ion")},
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
    assert abundance.levels["peptidoform_ion"].layers.get("intensity") == "Precursor_Quantity"
    assert abundance.levels["peptidoform_ion"].layers.keys() == {
        "intensity",
        "ms1_intensity",
        "normalized_intensity",
        "normalized_ms1_intensity",
    }
    older = Catalog("DIA-NN", "1.8.1", "confidence")
    assert older.levels["peptidoform_ion"].var.get("library_q_value") == "Lib_Q_Value"
    with pytest.raises(ValueError, match=r"no packaged DIA-NN rule admits version '9.0'"):
        Catalog("DIA-NN", "9.0", "abundance")


def test_catalog_names_roles_and_fixed_columns_of_the_apb_set() -> None:
    """A role's entry names the column the version's rule marks; a fixed name is that name."""
    apb = Catalog("DIA-NN", "2.6.0", "apb")
    assert apb.levels["peptidoform_ion"].var.get("protein_assignment") == "Protein_Group"
    assert apb.levels["peptidoform_ion"].var.get("peptidoform_ion") == "ProForma_ion"
    assert apb.levels["protein"].var.get("peptide") is None
    fields = apb.fields()
    assert fields.get_column("present").all()
    assert "concept" not in fields.columns


def test_data_catalog_finds_the_role_column_of_the_result() -> None:
    """The apb set names DIA-NN 2's protein-assignment column, which the result holds."""
    parsed = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised"],
        {"Protein_Group": ["P1", "P2"]},
        roles={"protein_assignment": "Protein_Group"},
    )
    found = DataCatalog(parsed, "apb").levels["peptidoform_ion"].var.get("protein_assignment")
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
    condition = catalog.levels["peptidoform_ion"].obs.get("group")
    assert condition is not None and condition.to_list() == ["A", "A", "B"]
    replicate = catalog.levels["peptidoform_ion"].obs.get("subject")
    assert replicate is not None and replicate.to_list() == ["s1", "s2", "s1"]
    plain = DataCatalog(_result("diann/v2/rules.json", ["Precursor_Normalised"], obs=obs), "apb")
    assert plain.levels["peptidoform_ion"].obs.get("group") is None, "no convention recorded"


def test_an_annotation_entry_of_every_level_is_one_table_row_and_a_column_per_level() -> None:
    """The long table keeps the entry's level ``*``; a result's fields name the level and the
    column it bound to."""
    table = catalogue_table("apb").filter(pl.col("entry_id").str.starts_with("annotation:"))
    assert set(table.get_column("level")) == {"*"}
    obs = {"group_condition": ["A", "A", "B"]}
    annotated = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised"],
        obs=obs,
        metadata={"prolfquapp": {"schema_version": "4"}},
    )
    fields = DataCatalog(annotated, "apb").fields().filter(pl.col("key") == "group")
    assert fields.select("level", "name", "entry_id").rows() == [
        (
            "peptidoform_ion",
            "group_condition",
            "annotation:prolfquapp/*/peptidoform_ion/obs/-/group_condition",
        )
    ]


def test_a_list_of_names_reads_every_column_a_prefix_binds() -> None:
    """A prolfquapp table with ``group`` and ``bait`` columns has two conditions."""
    obs = {"group_x": ["A", "A", "B"], "bait": ["b1", "b2", "b1"], "subject": ["s1", "s2", "s1"]}
    annotated = _result(
        "diann/v2/rules.json",
        ["Precursor_Normalised"],
        obs=obs,
        metadata={"prolfquapp": {"schema_version": "4"}},
    )
    level = DataCatalog(annotated, "apb").levels["peptidoform_ion"]
    with pytest.raises(UnresolvedField, match="ambiguous"):
        level.obs["group"]
    design = level.obs[["group", "subject", "Run"]]
    assert design.columns == ["group_x", "bait", "subject", "Run"]


def test_catalog_levels_hold_names() -> None:
    """The slots of a data catalog's levels, holding names: no data, so no own names."""
    abundance = Catalog("DIA-NN", "2.6.0", "abundance")
    assert list(abundance.levels) == ["peptidoform_ion", "protein"]
    ion = abundance.levels["peptidoform_ion"]
    assert ion.layers["intensity"] == "Precursor_Quantity"
    assert ion.layers.keys() == {
        "intensity",
        "ms1_intensity",
        "normalized_intensity",
        "normalized_ms1_intensity",
    }
    with pytest.raises(KeyError, match="Precursor_Quantity"):
        ion.layers["Precursor_Quantity"]
    assert ion.layers.get("intensity") == ion.layers.name("intensity") == "Precursor_Quantity"
    assert ion.layers.get("Precursor_Quantity") is None
    apb = Catalog("DIA-NN", "2.6.0", "apb").levels["peptidoform_ion"]
    assert apb.var[["peptidoform_ion", "protein_assignment"]] == ("ProForma_ion", "Protein_Group")
    with pytest.raises(KeyError, match="peptide"):
        apb.layers["peptide"]


def test_a_catalog_answers_its_own_prefix_and_no_vendor_name() -> None:
    """Without data, ``a:`` asks the set as a plain key does; ``v:`` has no own name to read."""
    ion = Catalog("DIA-NN", "2.6.0", "abundance").levels["peptidoform_ion"]
    assert ion.layers["a:intensity"] == "Precursor_Quantity"
    assert "a:intensity" in ion.layers
    assert ion.layers.get("v:Precursor_Quantity") is None
    with pytest.raises(KeyError, match="'v:Precursor_Quantity'"):
        ion.layers["v:Precursor_Quantity"]
    with pytest.raises(ValueError, match=r"unknown prefix 'c'.*\['a', 'v'\]"):
        ion.layers.get("c:pep")


def test_enforce_required_warns_for_a_missing_recommended_field(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PEAKS has no un-normalized intensity: a warning, a summary entry, and no exception."""
    parsed = _result("peaks/rules.json", ["Normalized_Area"])
    catalog = DataCatalog(parsed, "abundance", enforce="required")
    with caplog.at_level(logging.WARNING, logger="apb_catalog"):
        found = catalog.levels["peptidoform_ion"].layers.get("intensity")
    assert found is None
    assert (
        "recommended field intensity (kind=intensity, normalization=none) on peptidoform_ion"
        in (caplog.text)
    )
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


def test_enforce_recommended_raises_for_a_missing_recommended_field() -> None:
    """``enforce="recommended"`` makes recommended fields binding too."""
    catalog = DataCatalog(
        _result("peaks/rules.json", ["Normalized_Area"]), "abundance", enforce="recommended"
    )
    with pytest.raises(MissingRequiredField, match="recommended field"):
        catalog.levels["peptidoform_ion"].layers.get("intensity")


def test_enforce_raises_for_a_missing_required_field() -> None:
    """A peptidoform-ion level without ``ProForma_peptide`` misses a required field of the apb set."""
    catalog = DataCatalog(
        _result("diann/v2/rules.json", ["Precursor_Normalised"]), "apb", enforce="required"
    )
    with pytest.raises(MissingRequiredField, match=r"required field peptide \(kind=peptide\)"):
        catalog.levels["peptidoform_ion"].var.get("peptide")
    assert (
        DataCatalog(_result("diann/v2/rules.json", ["Precursor_Normalised"]), "apb")
        .levels["peptidoform_ion"]
        .var.get("peptide")
        is None
    ), "without enforce, absence is None"


def test_enforce_needs_requirements() -> None:
    """A set without requirement rows has nothing to enforce; a data catalog composes apb's."""
    with pytest.raises(ValueError, match="sets no requirements"):
        Catalog("PEAKS", "13", "confidence", enforce="required")
    composed = DataCatalog(
        _result("peaks/rules.json", ["Normalized_Area"]), "confidence", enforce="required"
    )
    with pytest.raises(MissingRequiredField, match="required field peptide"):
        composed.levels["peptidoform_ion"].var.get("peptide")


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
    """One row per entry and software version, the qualifiers as columns, and no concept."""
    table = catalogue_table()
    assert table.columns[: len(KEY_COLUMNS)] == list(KEY_COLUMNS)
    assert table.columns[-2:] == ["requirement", "entry_id"]
    assert "concept" not in table.columns
    assert set(table.get_column("set")) == {
        "abundance",
        "confidence",
        "proteobench_entrapment",
        "apb",
        "chromatography",
    }
    library = table.filter((pl.col("set") == "confidence") & (pl.col("kind") == "library_q_value"))
    assert {"Lib_Q_Value", "EG_LibraryQvalue"} <= set(library.get_column("name"))
    duplicated = (
        table.group_by("set", "entry_id", "kind", "software_version_pattern")
        .len()
        .filter(pl.col("len") > 1)
    )
    assert duplicated.is_empty(), "set, entry id, kind and software version pattern identify a row"
