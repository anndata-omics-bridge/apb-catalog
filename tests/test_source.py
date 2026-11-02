"""Packaged catalogue sets must stay consistent with the vocabulary and with what APB2 ships."""

from __future__ import annotations

import pytest
from apb2.api import FIXED_COLUMNS, VAR_ROLES

from apb_catalog.source import (
    CatalogueDescription,
    Evidence,
    ProducerCatalogue,
    Reference,
    RuleVariant,
    SourceCatalogue,
    SourceCatalogues,
    SourceEntry,
    packaged_catalogues,
    packaged_descriptions,
)
from tests.packaged_rules import (
    abundance_layers,
    declared_roles,
    declared_software_versions,
    declared_var_column,
    effective_rules,
    retained_sources,
    rule_of,
)

CONFIDENCE = packaged_catalogues("confidence").vocabulary
DESCRIPTION = CatalogueDescription(purpose="Test entries.", used_by=("tests",))

ION = RuleVariant(level="peptidoform_ion", software_version_pattern="^1\\.")


def _catalogues(name: str) -> tuple[SourceCatalogue, ...]:
    return packaged_catalogues(name).catalogues


def _entry(name: str, **qualifiers: str) -> SourceEntry:
    return SourceEntry(
        entry_id=f"vendor.peptidoform_ion.{name}",
        software_version_pattern=("^1\\.",),
        reference=Reference(level="peptidoform_ion", location="layers", name=name),
        qualifiers={"kind": "pep", "stage": "identification"} | qualifiers,
        evidence=Evidence(basis="test"),
    )


def _catalogue(*entries: SourceEntry, **overrides: object) -> SourceCatalogue:
    fields: dict[str, object] = {
        "software_name": "Vendor",
        "variants": (ION,),
        "entries": entries,
    } | overrides
    return SourceCatalogue.model_validate(fields)


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_packaged_catalogues_load_against_the_vocabulary(name: str) -> None:
    """Every packaged entry is fully described in its set's vocabulary."""
    assert packaged_catalogues(name).reviewed("Vendor", "^0\\.", "peptidoform_ion") is None


def test_an_unknown_catalogue_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown catalogue"):
        packaged_catalogues("everything")


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_entries_name_fields_the_rules_retain(name: str) -> None:
    """Every entry refers to an APB output name the rule of each of its versions retains."""
    missing = [
        f"{entry.entry_id} under {pattern}"
        for catalogue in _catalogues(name)
        for entry in catalogue.entries
        for pattern in entry.software_version_pattern
        if (entry.reference.location, entry.reference.name)
        not in retained_sources(
            rule_of(catalogue.software_name, pattern, entry.reference.level),
            entry.reference.level,
        )
    ]
    assert missing == []


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_every_packaged_rule_level_is_reviewed(name: str) -> None:
    """A new software version needs a catalogue, even one recording that nothing is relevant."""
    if not _catalogues(name):
        pytest.skip("a set without vendor catalogues needs no review")
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
    assert reviewed == packaged


ABUNDANCE_LEFT_OUT = {
    # DIA-NN's gene-group quantity sits on the protein-group level, which answers for its own entity.
    ("protein", "Genes_MaxLFQ"),
    # One entry per kind: AlphaPept's MS1 sum over the peak area is its intensity; the apex and
    # maximum variants stay readable by name.
    ("peptidoform_ion", "MS1_Int_Sum_Apex"),
    ("peptidoform_ion", "MS1_Int_Max_Area"),
    ("peptidoform_ion", "MS1_Int_Max_Apex"),
    # Spectronaut's fragment peak area is its intensity; the peak height stays readable by name.
    ("peptidoform_fragment", "F_PeakHeight"),
    # Spectronaut's elution-group quantities under the run's settings are not the precursor's own
    # quantity, FG_Quantity; they stay readable by name.
    ("peptidoform_ion", "EG_TotalQuantity_Settings"),
    ("peptidoform_ion", "EG_TargetQuantity_Settings"),
    ("peptidoform_ion", "EG_ReferenceQuantity_Settings"),
}
"""Abundance-role layers the catalog leaves out; one kind has at most one entry per rule level."""


def test_abundance_entries_are_the_layers_apb2_marks_abundance() -> None:
    """A new abundance layer in an APB2 rule fails here until a reviewer catalogues it."""
    catalogued = {
        (rule_of(catalogue.software_name, pattern, entry.reference.level), level, name)
        for catalogue in _catalogues("abundance")
        for entry in catalogue.entries
        for pattern in entry.software_version_pattern
        for level, name in [(entry.reference.level, entry.reference.name)]
    }
    marked = {
        (rule, level, name)
        for rule, level in effective_rules()
        for name in abundance_layers(rule, level)
        if (level, name) not in ABUNDANCE_LEFT_OUT
    }
    assert catalogued == marked


def test_a_kind_has_at_most_one_vendor_entry_per_rule_level() -> None:
    """The catalog picks one layer per kind; a kind it cannot name, ``unknown``, may repeat."""
    seen: dict[tuple[str, str, str, str, str], str | None] = {}
    repeated: list[tuple[str, str, str, str, str, str | None, str | None]] = []
    for catalogue in _catalogues("abundance"):
        for entry in catalogue.entries:
            kind = entry.qualifiers["kind"]
            if kind == "unknown":
                continue
            for pattern in entry.software_version_pattern:
                reference = entry.reference
                key = (catalogue.software_name, pattern, reference.level, reference.location, kind)
                if key in seen:
                    repeated.append((*key, seen[key], entry.reference.name))
                seen[key] = entry.reference.name
    assert repeated == []


def test_an_entry_must_use_a_declared_rule_variant() -> None:
    """An entry cannot claim a software version the catalogue never reviewed."""
    stray = _entry("PEP").model_copy(update={"software_version_pattern": ("^9\\.",)})
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
        SourceCatalogues(CONFIDENCE, "test", (_catalogue(partial),), DESCRIPTION)


def test_entry_qualifier_values_must_be_admitted() -> None:
    """A value outside the vocabulary is rejected, while ``unknown`` is accepted."""
    SourceCatalogues(CONFIDENCE, "test", (_catalogue(_entry("PEP", stage="unknown")),), DESCRIPTION)
    with pytest.raises(ValueError, match="does not admit"):
        SourceCatalogues(CONFIDENCE, "test", (_catalogue(_entry("PEP", kind="fdr")),), DESCRIPTION)


def test_a_software_version_is_reviewed_by_one_catalogue_only() -> None:
    """One software version's level cannot be bound to two vendor catalogues of one set."""
    first = _catalogue(_entry("PEP"))
    second = _catalogue()
    with pytest.raises(ValueError, match="reviewed more than once"):
        SourceCatalogues(CONFIDENCE, "test", (first, second), DESCRIPTION)


def test_an_entry_id_repeats_nowhere_in_a_set() -> None:
    """Vendor and app entries share one id space, so a snapshot names each unambiguously."""
    later = RuleVariant(level="peptidoform_ion", software_version_pattern="^2\\.")
    first = _catalogue(_entry("PEP"))
    second = _catalogue(
        _entry("PEP").model_copy(update={"software_version_pattern": ("^2\\.",)}),
        variants=(later,),
    )
    with pytest.raises(ValueError, match="repeats"):
        SourceCatalogues(CONFIDENCE, "test", (first, second), DESCRIPTION)


def _producer(*entries: SourceEntry, **overrides: object) -> ProducerCatalogue:
    fields: dict[str, object] = {
        "producer": "tool",
        "requires": ("tool", "provenance"),
        "instruction": "run `tool`",
        "entries": entries,
    } | overrides
    return ProducerCatalogue.model_validate(fields)


def test_app_entries_apply_to_every_software_version() -> None:
    """An app writes its fields whatever the software, so its entries name no version."""
    with pytest.raises(ValueError, match="apply to every software version"):
        _producer(_entry("PEP"))
    unversioned = _entry("PEP").model_copy(update={"software_version_pattern": ()})
    assert _producer(unversioned).entries_on("peptidoform_ion")


def test_a_required_run_comes_with_an_instruction() -> None:
    """A pending answer must say what to run."""
    with pytest.raises(ValueError, match="instruction"):
        _producer(instruction=None)
    with pytest.raises(ValueError, match="instruction"):
        _producer(requires=())


def test_a_producer_ran_when_the_result_records_it() -> None:
    """The run is read from the metadata path the producer records it at."""
    producer = _producer()
    assert producer.ran({"tool": {"provenance": {}}})
    assert not producer.ran({})
    assert not producer.ran({"tool": ["provenance"]})
    assert _producer(requires=(), instruction=None).ran({})
    assert producer.pending_reason() == "tool has not run on this result; run `tool`"


def test_a_varm_reference_names_its_table() -> None:
    """A varm field lives in one named table; a var or layer field in none."""
    Reference(level="peptidoform_ion", location="varm", name="flag", table="fasta_validation")
    with pytest.raises(ValueError, match="table"):
        Reference(level="peptidoform_ion", location="varm", name="flag")
    with pytest.raises(ValueError, match="table"):
        Reference(level="peptidoform_ion", location="var", name="flag", table="fasta_validation")


DOMAIN_SETS = tuple(name for name in packaged_descriptions() if name != "apb")
"""The sets that catalogue the vendors' own columns; ``apb`` catalogues the columns APB2 writes."""


@pytest.mark.parametrize("name", DOMAIN_SETS)
def test_domain_sets_hold_no_apb2_columns(name: str) -> None:
    """APB2's canonical ProForma columns belong to the apb set, not to a domain set."""
    canonical = [
        entry.entry_id
        for catalogue in _catalogues(name)
        for entry in catalogue.entries
        if (entry.reference.name or "").startswith("ProForma_")
    ]
    assert canonical == []


@pytest.mark.parametrize("name", DOMAIN_SETS)
def test_vendor_flags_answer_only_where_the_rule_reads_the_vendor(name: str) -> None:
    """A decoy or contaminant flag with no vendor input is false by declaration, not reported."""
    constant = [
        f"{entry.entry_id} under {pattern}"
        for catalogue in _catalogues(name)
        for entry in catalogue.entries
        if entry.reference.name in ("apb_Decoy", "apb_Contaminant")
        for pattern in entry.software_version_pattern
        if not declared_var_column(
            rule_of(catalogue.software_name, pattern, entry.reference.level),
            entry.reference.level,
            entry.reference.name,
        ).get("inputs")
    ]
    assert constant == []


def _apb_columns() -> set[tuple[str, str, str, str, str]]:
    """Every (software, pattern, level, column, kind) the apb set catalogues."""
    return {
        (catalogue.software_name, pattern, entry.reference.level, name, entry.qualifiers["kind"])
        for catalogue in _catalogues("apb")
        for entry in catalogue.entries
        for pattern in entry.software_version_pattern
        for name in [entry.reference.name or ""]
    }


def test_apb_entries_name_fixed_columns_or_role_columns() -> None:
    """Every apb entry names a column APB2 fixes, or the column the rule marks with the role its
    kind names."""
    unwritten = [
        (software, pattern, level, name, kind)
        for software, pattern, level, name, kind in _apb_columns()
        if name not in FIXED_COLUMNS
        and declared_roles(rule_of(software, pattern, level), level).get(kind) != name
    ]
    assert unwritten == []


def test_every_fixed_and_role_column_a_rule_writes_has_an_apb_entry() -> None:
    """A new rule level fails here until the apb set names APB2's columns for it."""
    catalogued = {
        (software, pattern, level, name) for software, pattern, level, name, _ in _apb_columns()
    }
    written = {
        (software, pattern, level, name)
        for rule, level in effective_rules()
        for software, pattern in declared_software_versions(rule, level)
        for location, name in retained_sources(rule, level)
        if location == "var" and name in FIXED_COLUMNS
    } | {
        (software, pattern, level, column)
        for rule, level in effective_rules()
        for software, pattern in declared_software_versions(rule, level)
        for role, column in declared_roles(rule, level).items()
        if role in VAR_ROLES
    }
    assert written - catalogued == set()


def test_every_fixed_column_and_var_role_has_an_apb_kind() -> None:
    """The apb set drifts from apb2 the moment apb2 fixes a new name or adds a var role."""
    columns = _apb_columns()
    assert {name for _, _, _, name, _ in columns} >= set(FIXED_COLUMNS)
    assert {kind for _, _, _, _, kind in columns} >= set(VAR_ROLES)
