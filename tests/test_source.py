"""Packaged catalogues must stay consistent with the vocabulary and with what APB2 ships."""

from __future__ import annotations

import re
from importlib import resources
from importlib.resources.abc import Traversable

import pytest

from apb_catalog.source import (
    Evidence,
    Reference,
    Review,
    RuleVariant,
    SourceCatalogue,
    SourceCatalogues,
    SourceEntry,
    UnmappedField,
    packaged_catalogues,
)
from apb_catalog.vocabulary import packaged_vocabulary
from tests.packaged_rules import current_fingerprints, effective_rules, retained_sources

CONFIDENCE_LIKE = re.compile(r"(^|_)(pep|q_?value|\w*qvalue|\w*score)(_|$)", re.IGNORECASE)
REVIEW = Review(date="2026-09-30", apb2_revision="test")
ION = RuleVariant(rule="vendor/rules.json", level="ion", fingerprints=("sha256:ion",))


def _catalogues() -> list[SourceCatalogue]:
    return [
        SourceCatalogue.model_validate_json(path.read_text("utf-8"))
        for path in sorted(_source_directory().iterdir(), key=lambda path: path.name)
    ]


def _source_directory() -> Traversable:
    return resources.files("apb_catalog").joinpath("data", "sources")


def _entry(name: str, **qualifiers: str) -> SourceEntry:
    described = {
        "kind": "pep",
        "entity": "precursor",
        "statistic": "value",
        "direction": "lower_better",
        "stage": "identification",
    } | qualifiers
    return SourceEntry(
        entry_id=f"vendor.ion.{name}",
        rules=("vendor/rules.json",),
        reference=Reference(level="ion", location="layers", name=name),
        vendor_source=name,
        concept="confidence",
        qualifiers=described,
        evidence=Evidence(basis="test"),
    )


def _catalogue(*entries: SourceEntry, **overrides: object) -> SourceCatalogue:
    fields: dict[str, object] = {
        "catalogue_id": "vendor",
        "catalogue_version": "0.1",
        "software_name": "Vendor",
        "review": REVIEW,
        "variants": (ION,),
        "entries": entries,
    } | overrides
    return SourceCatalogue.model_validate(fields)


def test_packaged_catalogues_load_against_the_vocabulary() -> None:
    """Every packaged entry names a declared concept with fully described qualifiers."""
    catalogues = packaged_catalogues()
    assert catalogues.reviewed("sha256:not-reviewed") is None


def test_reviewed_fingerprints_match_the_rules_apb2_ships() -> None:
    """A changed APB2 rule must be re-reviewed before its fields regain catalogued meaning."""
    drift = {
        (variant.rule, variant.level): sorted(current_fingerprints(variant.rule, variant.level))
        for catalogue in _catalogues()
        for variant in catalogue.variants
        if set(variant.fingerprints) != current_fingerprints(variant.rule, variant.level)
    }
    assert drift == {}, f"re-review these rule variants; current fingerprints: {drift}"


def test_entries_name_retained_fields_with_their_vendor_source() -> None:
    """Every entry and gap refers to an APB output name the rule retains, from that source."""
    wrong: list[str] = []
    for catalogue in _catalogues():
        for entry in catalogue.entries:
            for rule in entry.rules:
                sources = retained_sources(rule, entry.reference.level)
                key = (entry.reference.location, entry.reference.name)
                if sources.get(key) != entry.vendor_source:
                    wrong.append(f"{entry.entry_id} under {rule}: rule has {sources.get(key)!r}")
        for gap in catalogue.unmapped:
            for rule in gap.rules:
                key = (gap.reference.location, gap.reference.name)
                if key not in retained_sources(rule, gap.reference.level):
                    wrong.append(f"unmapped {gap.reference.name} is not retained by {rule}")
    assert wrong == []


def test_every_confidence_like_field_of_a_reviewed_rule_is_accounted_for() -> None:
    """New PEP, q-value or score fields in a reviewed rule need an entry or a stated gap."""
    unaccounted: list[str] = []
    for catalogue in _catalogues():
        for variant in catalogue.variants:
            covered = {
                (field.reference.location, field.reference.name)
                for field in (*catalogue.entries, *catalogue.unmapped)
                if variant.rule in field.rules and field.reference.level == variant.level
            }
            for location, name in retained_sources(variant.rule, variant.level):
                if CONFIDENCE_LIKE.search(name) and (location, name) not in covered:
                    unaccounted.append(f"{variant.rule} {variant.level} {location}/{name}")
    assert unaccounted == []


def test_an_entry_must_use_a_declared_rule_variant() -> None:
    """An entry cannot claim a rule level the catalogue never reviewed."""
    stray = _entry("PEP").model_copy(update={"rules": ("other/rules.json",)})
    with pytest.raises(ValueError, match="uses"):
        _catalogue(stray)


def test_entry_ids_are_unique() -> None:
    """Two entries cannot share one identifier."""
    with pytest.raises(ValueError, match="duplicate entry ids"):
        _catalogue(_entry("PEP"), _entry("PEP"))


def test_a_field_cannot_be_both_mapped_and_unmapped() -> None:
    """A deliberate gap contradicts an entry for the same field."""
    gap = UnmappedField(
        rules=("vendor/rules.json",),
        reference=Reference(level="ion", location="layers", name="PEP"),
        reason="test",
    )
    with pytest.raises(ValueError, match="both mapped and unmapped"):
        _catalogue(_entry("PEP"), unmapped=(gap,))


def test_entry_qualifiers_must_describe_every_vocabulary_qualifier() -> None:
    """Leaving a qualifier out is rejected; ``unknown`` must be recorded explicitly."""
    partial = _entry("PEP").model_copy(update={"qualifiers": {"kind": "pep"}})
    with pytest.raises(ValueError, match="qualifiers must be exactly"):
        SourceCatalogues(packaged_vocabulary(), (_catalogue(partial),))


def test_entry_qualifier_values_must_be_admitted() -> None:
    """A value outside the vocabulary is rejected, while ``unknown`` is accepted."""
    SourceCatalogues(packaged_vocabulary(), (_catalogue(_entry("PEP", statistic="unknown")),))
    with pytest.raises(ValueError, match="does not admit"):
        SourceCatalogues(packaged_vocabulary(), (_catalogue(_entry("PEP", kind="fdr")),))


def test_a_fingerprint_is_reviewed_by_one_catalogue_only() -> None:
    """One effective rule cannot be bound to two catalogues."""
    first = _catalogue(_entry("PEP"))
    second = _catalogue(_entry("PEP"), catalogue_id="other")
    with pytest.raises(ValueError, match="reviewed more than once"):
        SourceCatalogues(packaged_vocabulary(), (first, second))


def test_every_packaged_rule_level_is_reviewed() -> None:
    """A new APB2 rule needs a catalogue, even one recording that it retains no confidence."""
    reviewed = {(variant.rule, variant.level) for c in _catalogues() for variant in c.variants}
    assert set(effective_rules()) - reviewed == set()
