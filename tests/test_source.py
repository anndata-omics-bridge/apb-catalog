"""Packaged catalogue sets must stay consistent with the vocabulary and with what APB2 ships."""

from __future__ import annotations

from importlib import resources

import pytest

from apb_catalog.source import (
    CatalogueDescription,
    Evidence,
    Reference,
    RuleVariant,
    SourceCatalogue,
    SourceCatalogues,
    SourceEntry,
    packaged_catalogues,
    packaged_descriptions,
)
from apb_catalog.vocabulary import packaged_vocabulary
from tests.packaged_rules import declared_software_versions, effective_rules, retained_sources

DESCRIPTION = CatalogueDescription(purpose="Test entries.", used_by=("tests",))

ION = RuleVariant(rule="vendor/rules.json", level="ion", software_version_pattern="^1\\.")


def _catalogues(name: str) -> list[SourceCatalogue]:
    directory = resources.files("apb_catalog").joinpath("data", "sources", name)
    return [
        SourceCatalogue.model_validate_json(path.read_text("utf-8"))
        for path in sorted(directory.iterdir(), key=lambda path: path.name)
    ]


def _entry(name: str, **qualifiers: str) -> SourceEntry:
    return SourceEntry(
        entry_id=f"vendor.ion.{name}",
        rules=("vendor/rules.json",),
        reference=Reference(level="ion", location="layers", name=name),
        concept="confidence",
        qualifiers={"kind": "pep", "stage": "identification"} | qualifiers,
        evidence=Evidence(basis="test"),
    )


def _catalogue(*entries: SourceEntry, **overrides: object) -> SourceCatalogue:
    fields: dict[str, object] = {
        "catalogue_id": "vendor",
        "catalogue_version": "0.1",
        "software_name": "Vendor",
        "variants": (ION,),
        "entries": entries,
    } | overrides
    return SourceCatalogue.model_validate(fields)


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_packaged_catalogues_load_against_the_vocabulary(name: str) -> None:
    """Every packaged entry names a declared concept with fully described qualifiers."""
    assert packaged_catalogues(name).reviewed("Vendor", "^0\\.", "ion") is None


def test_an_unknown_catalogue_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown catalogue"):
        packaged_catalogues("everything")


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_variants_name_the_software_and_version_their_rules_declare(name: str) -> None:
    """Levels bind by software name and version, so each variant states its rule's pair."""
    wrong = {
        (variant.rule, variant.level): sorted(
            declared_software_versions(variant.rule, variant.level)
        )
        for catalogue in _catalogues(name)
        for variant in catalogue.variants
        if declared_software_versions(variant.rule, variant.level)
        != {(catalogue.software_name, variant.software_version_pattern)}
    }
    assert wrong == {}, f"these variants disagree with their rules: {wrong}"


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_entries_name_fields_the_rules_retain(name: str) -> None:
    """Every entry refers to an APB output name each of its rules retains."""
    missing = [
        f"{entry.entry_id} under {rule}"
        for catalogue in _catalogues(name)
        for entry in catalogue.entries
        for rule in entry.rules
        if (entry.reference.location, entry.reference.name)
        not in retained_sources(rule, entry.reference.level)
    ]
    assert missing == []


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_every_packaged_rule_level_is_reviewed(name: str) -> None:
    """A new software version needs a catalogue, even one recording that nothing is relevant.

    Levels bind by software name and version, so two rules declaring both, such as MaxQuant's
    ``maxquant`` and ``maxquant_wide``, share one variant.
    """
    reviewed = {
        (c.software_name, variant.software_version_pattern, variant.level)
        for c in _catalogues(name)
        for variant in c.variants
    }
    packaged = {
        (software, version, level)
        for rule, level in effective_rules()
        for software, version in declared_software_versions(rule, level)
    }
    assert packaged - reviewed == set()


def test_an_entry_must_use_a_declared_rule_variant() -> None:
    """An entry cannot claim a rule level the catalogue never reviewed."""
    stray = _entry("PEP").model_copy(update={"rules": ("other/rules.json",)})
    with pytest.raises(ValueError, match="uses"):
        _catalogue(stray)


def test_entry_ids_are_unique() -> None:
    """Two entries cannot share one identifier."""
    with pytest.raises(ValueError, match="duplicate entry ids"):
        _catalogue(_entry("PEP"), _entry("PEP"))


def test_entry_qualifiers_must_describe_every_vocabulary_qualifier() -> None:
    """Leaving a qualifier out is rejected; ``unknown`` must be recorded explicitly."""
    partial = _entry("PEP").model_copy(update={"qualifiers": {"kind": "pep"}})
    with pytest.raises(ValueError, match="qualifiers must be exactly"):
        SourceCatalogues(packaged_vocabulary(), (_catalogue(partial),), DESCRIPTION)


def test_entry_qualifier_values_must_be_admitted() -> None:
    """A value outside the vocabulary is rejected, while ``unknown`` is accepted."""
    SourceCatalogues(
        packaged_vocabulary(), (_catalogue(_entry("PEP", stage="unknown")),), DESCRIPTION
    )
    with pytest.raises(ValueError, match="does not admit"):
        SourceCatalogues(
            packaged_vocabulary(), (_catalogue(_entry("PEP", kind="fdr")),), DESCRIPTION
        )


def test_a_software_version_is_reviewed_by_one_catalogue_only() -> None:
    """One software version's level cannot be bound to two vendor catalogues of one set."""
    first = _catalogue(_entry("PEP"))
    second = _catalogue(_entry("PEP"), catalogue_id="other")
    with pytest.raises(ValueError, match="reviewed more than once"):
        SourceCatalogues(packaged_vocabulary(), (first, second), DESCRIPTION)
