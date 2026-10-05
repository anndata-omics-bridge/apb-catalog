"""Callers ask a result for a meaning and get the data; snapshots survive every format."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from apb2.api import (
    JsonValue,
    ParsedLevel,
    ParsedLevels,
    read_parsed_levels,
    write_parsed_levels,
)
from polars.testing import assert_frame_equal

from apb_catalog.catalog import (
    METADATA_KEY,
    Catalog,
    attach_snapshot,
    stale_levels,
    stored_snapshot,
)
from apb_catalog.resolver import ReviewedBinding, UnresolvedField, UnreviewedBinding
from apb_catalog.source import packaged_descriptions
from tests.packaged_rules import declared_rule_json

type VarColumns = Mapping[str, Sequence[float] | Sequence[str]]

KEYS: dict[str, str] = {"ion": "ProForma_ion", "protein": "Protein_Group"}


def _level(
    level: str, rule_json: str | None, layers: Sequence[str], var: VarColumns
) -> ParsedLevel:
    obs = pl.DataFrame({"Run": ["R1", "R2", "R3"]})
    key = KEYS[level]
    features = pl.DataFrame(
        {key: ["F1", "F2"], **{name: list(values) for name, values in var.items()}}
    )
    values = {
        name: pl.DataFrame(
            {f"c{column}": [float(offset + 1) / 10 + column] * 2 for column in range(obs.height)}
        )
        for offset, name in enumerate(layers)
    }
    uns: dict[str, JsonValue] = {"produced_by": "apb2", "quantification_level": level}
    if rule_json is not None:
        uns["rule_json"] = rule_json
    return ParsedLevel.build(
        obs, ("Run",), features, (key,), {}, primary_layer=layers[0], abundance=values, uns=uns
    )


def _result(
    rule: str | None,
    layers: Sequence[str],
    var: VarColumns | None = None,
    level: str = "ion",
) -> ParsedLevels:
    rule_json = declared_rule_json(rule, level) if rule is not None else None
    return ParsedLevels(levels={level: _level(level, rule_json, layers, var or {})}, uns={})


def _edited_maxquant(**changes: object) -> ParsedLevels:
    edited = json.loads(declared_rule_json("maxquant_wide/rules.json", "ion"))
    edited.update(changes)
    return ParsedLevels(
        levels={"ion": _level("ion", json.dumps(edited), ["Intensity", "PEP"], {})}, uns={}
    )


MAXQUANT = ("maxquant_wide/rules.json", ["Intensity", "PEP", "Score"])
SPECTRONAUT = ("spectronaut/rules.json", ["FG_Quantity", "EG_PEP", "EG_Qvalue", "FG_Qvalue"])


def test_the_same_call_returns_each_vendors_layer() -> None:
    """Callers never name ``PEP`` or ``EG_PEP``; the catalogue does."""
    maxquant = _result(*MAXQUANT)
    spectronaut = _result(*SPECTRONAUT)
    pep = {"concept": "confidence", "kind": "pep"}
    assert (
        Catalog(maxquant, "identification_confidence").layer("ion", **pep)
        is maxquant.levels["ion"].layers["PEP"]
    )
    found = Catalog(spectronaut, "identification_confidence").layer("ion", **pep)
    assert found is spectronaut.levels["ion"].layers["EG_PEP"]


def test_only_the_fields_the_consumer_needs_are_catalogued() -> None:
    """Spectronaut's EG and FG q-values agree; aggregation is given the EG one only."""
    parsed = _result(*SPECTRONAUT)
    found = Catalog(parsed, "identification_confidence").layer(
        "ion", concept="confidence", kind="q_value"
    )
    assert found is parsed.levels["ion"].layers["EG_Qvalue"]


def test_a_vendor_without_the_field_returns_none() -> None:
    """DIA-NN without its PEP layer is a reviewed absence, not an error."""
    parsed = _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"])
    catalog = Catalog(parsed, "identification_confidence")
    assert catalog.layer("ion", concept="confidence", kind="pep") is None
    assert (
        catalog.layer("ion", concept="confidence", kind="q_value")
        is parsed.levels["ion"].layers["Q_Value"]
    )


def test_quantification_confidence_is_found_only_when_asked_for() -> None:
    """Sage's q-value rates the MS1 peak, one value per feature."""
    parsed = _result("sage/rules.json", ["Intensity"], {"Q_Value": [0.001, 0.002]})
    catalog = Catalog(parsed, "identification_confidence")
    assert catalog.var("ion", concept="confidence", kind="q_value") is None
    column = catalog.var("ion", concept="confidence", kind="q_value", stage="quantification")
    assert column is not None
    assert column.to_list() == [0.001, 0.002]


def test_miape_names_the_columns_mipae_anndata_expects() -> None:
    """DIA-NN's protein columns are found by their MIAPE-AnnData field names."""
    parsed = _result(
        "diann/v2/rules.json",
        ["PG_MaxLFQ", "Genes_MaxLFQ"],
        {"Genes": ["G1", "G2"], "Protein_Ids": ["P1", "P2"]},
        level="protein",
    )
    catalog = Catalog(parsed, "miape")
    assert catalog.var("protein", concept="miape") == ("gene_name", "protein_group")
    assert catalog.layer("protein", concept="miape") == ("raw",)
    genes = catalog.var("protein", concept="miape", kind="gene_name")
    assert genes is not None
    assert genes.to_list() == ["G1", "G2"]
    raw = catalog.layer("protein", concept="miape", kind="raw")
    assert raw is parsed.levels["protein"].layers["PG_MaxLFQ"]


def test_an_ion_level_has_no_miape_modality() -> None:
    """MIAPE-AnnData defines protein, peptide, peptidoform and site modalities, not precursors."""
    catalog = Catalog(_result(*MAXQUANT), "miape")
    assert catalog.layer("ion", concept="miape") is None
    assert catalog.var("ion", concept="miape") is None


def test_an_unknown_catalogue_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown catalogue"):
        Catalog(_result(*MAXQUANT), "everything")


def test_an_unreviewed_level_raises() -> None:
    """Without a reviewed rule the catalogue cannot even claim absence."""
    with pytest.raises(UnresolvedField, match=r"unknown.*rule_json"):
        Catalog(_result(None, ["Intensity"]), "identification_confidence").layer(
            "ion", concept="confidence", kind="pep"
        )


def test_an_unreviewed_software_version_is_unknown() -> None:
    """A software version no catalogue variant names answers unknown."""
    with pytest.raises(UnresolvedField, match="no source catalogue reviewed"):
        Catalog(
            _edited_maxquant(software_version_pattern="^99\\."), "identification_confidence"
        ).layer("ion", concept="confidence", kind="pep")


def test_an_edited_rule_keeps_its_entries() -> None:
    """Levels bind by software and version, so editing a rule within a version changes nothing."""
    parsed = _edited_maxquant(file_version=-1)
    pep = Catalog(parsed, "identification_confidence").layer(
        "ion", concept="confidence", kind="pep"
    )
    assert pep is parsed.levels["ion"].layers["PEP"]


def test_an_absent_level_returns_none() -> None:
    """Asking about a level the result lacks is answered, not raised."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    assert catalog.layer("peptide", concept="confidence", kind="pep") is None


def test_an_unknown_kind_or_concept_is_rejected() -> None:
    """Misspellings fail loudly instead of matching nothing."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    with pytest.raises(ValueError, match="does not admit"):
        catalog.layer("ion", concept="confidence", kind="pepp")
    with pytest.raises(ValueError, match="unknown concept"):
        catalog.layer("ion", concept="abundance", kind="raw")


def test_leaving_out_kind_lists_the_kinds_on_offer() -> None:
    """Without ``kind`` the catalogue says what a level holds for the concept."""
    assert Catalog(_result(*MAXQUANT), "identification_confidence").layer(
        "ion", concept="confidence"
    ) == ("pep",)
    spectronaut = Catalog(_result(*SPECTRONAUT), "identification_confidence")
    assert spectronaut.layer("ion", concept="confidence") == ("pep", "q_value")
    dia_nn = Catalog(
        _result("diann/v2/rules.json", ["Precursor_Normalised", "Q_Value"]),
        "identification_confidence",
    )
    assert dia_nn.layer("ion", concept="confidence") == ("q_value",)
    assert dia_nn.var("ion", concept="confidence") is None


def test_listing_kinds_on_an_absent_or_unreviewed_level() -> None:
    """An absent level offers nothing; an unreviewed one cannot say."""
    assert (
        Catalog(_result(*MAXQUANT), "identification_confidence").layer(
            "peptide", concept="confidence"
        )
        is None
    )
    with pytest.raises(UnresolvedField, match="unknown"):
        Catalog(_result(None, ["Intensity"]), "identification_confidence").layer(
            "ion", concept="confidence"
        )


def test_listing_kinds_is_not_recorded_as_a_lookup() -> None:
    """Only lookups that return data enter the snapshot."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    catalog.layer("ion", concept="confidence")
    assert catalog.snapshot().resolutions == ()


def test_fields_lists_what_the_result_holds() -> None:
    """One row per catalogued field, readable without knowing the vendor."""
    fields = Catalog(_result(*MAXQUANT), "identification_confidence").fields()
    assert fields.select("location", "name", "kind").rows() == [("layers", "PEP", "pep")]


def test_the_snapshot_records_its_catalogue_bindings_and_lookups() -> None:
    """Every lookup is kept for the persisted record."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    catalog.layer("ion", concept="confidence", kind="pep")
    catalog.layer("ion", concept="confidence", kind="q_value")
    snapshot = catalog.snapshot()
    assert snapshot.catalogue == "identification_confidence"
    assert [resolution.status for resolution in snapshot.resolutions] == ["resolved", "missing"]
    binding = snapshot.levels[0]
    assert isinstance(binding, ReviewedBinding)
    assert (binding.software_name, binding.rule) == ("MaxQuant", "maxquant_wide/rules.json")
    unreviewed = Catalog(_result(None, ["Intensity"]), "identification_confidence").snapshot()
    assert isinstance(unreviewed.levels[0], UnreviewedBinding)


def test_snapshots_of_two_catalogues_sit_side_by_side() -> None:
    """Attaching one set's snapshot keeps the other's, and the input stays unchanged."""
    parsed = _result(*MAXQUANT)
    confidence = Catalog(parsed, "identification_confidence").snapshot()
    miape = Catalog(parsed, "miape").snapshot()
    attached = attach_snapshot(attach_snapshot(parsed, confidence), miape)
    assert METADATA_KEY not in parsed.metadata
    assert stored_snapshot(parsed, "identification_confidence") is None
    assert stored_snapshot(attached, "identification_confidence") == confidence
    assert stored_snapshot(attached, "miape") == miape
    assert attached.levels is parsed.levels


@pytest.mark.parametrize("suffix", [".h5ad", ".h5mu", ".parquet", ".duckdb"])
def test_snapshots_round_trip_every_storage_format(tmp_path: Path, suffix: str) -> None:
    """Stored snapshots read back identically and leave the scientific data untouched."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed, "identification_confidence")
    catalog.layer("ion", concept="confidence", kind="pep")
    snapshot = catalog.snapshot()
    target = tmp_path / f"result{suffix}"
    write_parsed_levels(attach_snapshot(parsed, snapshot), target)

    restored = read_parsed_levels(target)

    assert stored_snapshot(restored, "identification_confidence") == snapshot
    assert stale_levels(restored, snapshot) == ()
    for name, table in parsed.levels["ion"].layers.items():
        assert_frame_equal(restored.levels["ion"].layers[name].values, table.values)


def test_a_stored_snapshot_is_readable_as_plain_json(tmp_path: Path) -> None:
    """Consumers can follow the contract with apb2 and the standard library alone."""
    parsed = _result(*MAXQUANT)
    catalog = Catalog(parsed, "identification_confidence")
    catalog.layer("ion", concept="confidence", kind="pep")
    target = tmp_path / "result.h5mu"
    write_parsed_levels(attach_snapshot(parsed, catalog.snapshot()), target)

    namespace: dict[str, Any] = json.loads(
        json.dumps(read_parsed_levels(target).metadata["catalog"])
    )
    stored = namespace["identification_confidence"]

    assert stored["contract"] == "apb-catalog-resolution"
    answer = stored["resolutions"][0]
    assert answer["status"] == "resolved"
    assert answer["reference"] == {"level": "ion", "location": "layers", "name": "PEP"}
    entry = next(entry for entry in stored["entries"] if entry["reference"] == answer["reference"])
    assert entry["qualifiers"]["kind"] == "pep"


def test_a_changed_software_version_makes_the_snapshot_stale() -> None:
    """Snapshots record the software and version they were resolved against."""
    snapshot = Catalog(_result(*MAXQUANT), "identification_confidence").snapshot()
    assert stale_levels(_edited_maxquant(file_version=-1), snapshot) == ()
    stale = _edited_maxquant(software_version_pattern="^99\\.")
    assert stale_levels(stale, snapshot) == ("ion",)
    assert stale_levels(ParsedLevels(levels={}, uns={}), snapshot) == ("ion",)


def test_every_packaged_set_states_its_purpose_and_users() -> None:
    """Each sources directory has a description, and each description a sources directory."""
    sources = resources.files("apb_catalog").joinpath("data", "sources")
    directories = {path.name for path in sources.iterdir() if path.is_dir()}
    descriptions = packaged_descriptions()
    assert set(descriptions) == directories
    assert all(d.purpose and d.used_by for d in descriptions.values())


def test_snapshot_embeds_the_set_description() -> None:
    """A snapshot reader learns what the set is for without the package."""
    catalog = Catalog(_result(*MAXQUANT), "identification_confidence")
    assert catalog.snapshot().description == catalog.description
    assert "apb-aggregate" in catalog.description.used_by[0]


def test_proteobench_entrapment_offers_each_precursor_q_value_as_its_own_kind() -> None:
    """Entrapment ranks by run, library or experiment-wide q-values; each is one kind."""
    layers = ["Precursor_Normalised", "Q_Value", "Lib_Q_Value", "Global_Q_Value", "PEP"]
    parsed = _result("diann/v2/rules.json", layers)
    catalog = Catalog(parsed, "proteobench_entrapment")
    assert catalog.layer("ion", concept="confidence") == (
        "global_q_value",
        "library_q_value",
        "q_value",
    )
    found = catalog.layer("ion", concept="confidence", kind="library_q_value")
    assert found is parsed.levels["ion"].layers["Lib_Q_Value"]
    assert catalog.layer("ion", concept="confidence", kind="pep") is None, "PEP is not ranked by"
    assert (
        Catalog(_result(*MAXQUANT), "proteobench_entrapment").layer("ion", concept="confidence")
        is None
    )
