"""Packaged sets must stay consistent with the vocabulary, and each entry must name a
field APB2 writes."""

from __future__ import annotations

import pytest
from apb2.api import FIXED_COLUMNS

from apb_catalog.rules import EntryId, entry_id
from apb_catalog.source import (
    Evidence,
    Key,
    LoadedSet,
    ProducerEntries,
    Reference,
    RuleVariant,
    SetDescription,
    SourceEntry,
    VendorEntries,
    packaged_descriptions,
    packaged_set,
)
from tests.packaged_rules import (
    declared_roles,
    declared_var_column,
    retained_sources,
    rule_of,
)

CONFIDENCE = packaged_set("confidence_alpha").vocabulary
KEYS = packaged_set("confidence_alpha").keys
DESCRIPTION = SetDescription(purpose="Test entries.", used_by=("tests",))

ION = RuleVariant(level="peptidoform_ion", software_version_pattern="^1\\.")


def _vendors(name: str) -> tuple[VendorEntries, ...]:
    return packaged_set(name).vendors


def _entry(name: str, key: str = "pep", kind: str = "pep", **qualifiers: str) -> SourceEntry:
    return SourceEntry(
        entry_id=f"vendor.peptidoform_ion.{name}",
        software_version_pattern=("^1\\.",),
        reference=Reference(level="peptidoform_ion", location="layers", name=name),
        key=key,
        kind=kind,
        qualifiers={"stage": "identification"} | qualifiers,
        evidence=Evidence(basis="test"),
    )


def _vendor(*entries: SourceEntry, **overrides: object) -> VendorEntries:
    fields: dict[str, object] = {
        "software_name": "Vendor",
        "variants": (ION,),
        "entries": entries,
    } | overrides
    return VendorEntries.model_validate(fields)


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_packaged_sets_load_against_the_vocabulary(name: str) -> None:
    """Every packaged entry is fully described in its set's vocabulary."""
    assert packaged_set(name).reviewed("Vendor", "^0\\.", "peptidoform_ion") is None


def test_an_unknown_set_is_rejected() -> None:
    """Only the packaged consumer sets exist."""
    with pytest.raises(ValueError, match="unknown set"):
        packaged_set("everything")


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_entries_name_fields_the_rules_retain(name: str) -> None:
    """Every entry refers to an APB output name the rule of each of its versions retains."""
    missing = [
        f"{entry.entry_id} under {pattern}"
        for vendor in _vendors(name)
        for entry in vendor.entries
        for pattern in entry.software_version_pattern
        if (entry.reference.location, entry.reference.name)
        not in retained_sources(
            rule_of(vendor.software_name, pattern, entry.reference.level),
            entry.reference.level,
        )
    ]
    assert missing == []


@pytest.mark.parametrize(
    "name",
    ("abundance_alpha", "confidence_alpha", "proteobench_entrapment_alpha", "chromatography_alpha"),
)
def test_fields_sharing_a_key_on_a_rule_level_differ_in_a_qualifier(name: str) -> None:
    """A key and its qualifiers pick one field per location and software version; DIA-NN 1.x's
    protein PG_Normalised and PG_MaxLFQ share intensity_norm_settings and differ in aggregation."""
    seen: dict[tuple[object, ...], str | None] = {}
    repeated: list[tuple[object, ...]] = []
    for vendor in _vendors(name):
        for entry in vendor.entries:
            for pattern in entry.software_version_pattern:
                reference = entry.reference
                slot = (
                    vendor.software_name,
                    pattern,
                    reference.level,
                    reference.location,
                    entry.key,
                    tuple(sorted(entry.qualifiers.items())),
                )
                if slot in seen:
                    repeated.append((*slot, seen[slot], entry.reference.name))
                seen[slot] = entry.reference.name
    assert repeated == []


@pytest.mark.parametrize("name", tuple(packaged_descriptions()))
def test_every_entry_is_described_by_its_key(name: str) -> None:
    """Each entry carries the kind and the fixed values of the key it records."""
    sources = packaged_set(name)
    mismatched = [
        entry.entry_id
        for source in sources.sources()
        for entry in source.entries
        if not sources.key(entry.key).describes(entry.kind, entry.qualifiers)
    ]
    assert mismatched == []


def test_an_entry_must_carry_its_keys_meaning() -> None:
    """An entry whose key the set lacks, or whose key fixes another value, is refused; a second
    key that also describes it is not."""
    open_pep = Key(key="any_pep", kind="pep")
    other_stage = Key(key="pep", kind="pep", fixed={"stage": "quantification"})
    with pytest.raises(ValueError, match="does not describe it"):
        LoadedSet(CONFIDENCE, "test", (_vendor(_entry("PEP")),), DESCRIPTION, keys=())
    with pytest.raises(ValueError, match="does not describe it"):
        LoadedSet(CONFIDENCE, "test", (_vendor(_entry("PEP")),), DESCRIPTION, keys=(other_stage,))
    both = LoadedSet(
        CONFIDENCE, "test", (_vendor(_entry("PEP")),), DESCRIPTION, keys=(*KEYS, open_pep)
    )
    assert both.key("any_pep").describes("pep", {"stage": "identification"})


def test_a_key_names_admitted_values_once() -> None:
    """A key's kind and fixed values are the vocabulary's, and its name repeats nowhere."""
    with pytest.raises(ValueError, match="does not admit"):
        LoadedSet(CONFIDENCE, "test", (), DESCRIPTION, keys=(Key(key="fdr", kind="fdr"),))
    with pytest.raises(ValueError, match="repeats"):
        LoadedSet(CONFIDENCE, "test", (), DESCRIPTION, keys=(*KEYS, KEYS[0]))


def test_an_entry_must_use_a_declared_rule_variant() -> None:
    """An entry cannot claim a software version the set never reviewed."""
    stray = _entry("PEP").model_copy(update={"software_version_pattern": ("^9\\.",)})
    with pytest.raises(ValueError, match="uses"):
        _vendor(stray)


def test_entry_ids_are_unique() -> None:
    """Two entries cannot share one identifier."""
    with pytest.raises(ValueError, match="duplicate entry ids"):
        _vendor(_entry("PEP"), _entry("PEP"))


def test_entry_qualifiers_must_describe_every_vocabulary_qualifier() -> None:
    """Leaving a qualifier out is rejected; ``unknown`` must be recorded explicitly."""
    partial = _entry("PEP").model_copy(update={"qualifiers": {}})
    with pytest.raises(ValueError, match="qualifiers must be exactly"):
        LoadedSet(CONFIDENCE, "test", (_vendor(partial),), DESCRIPTION, keys=KEYS)


def test_entry_qualifier_values_must_be_admitted() -> None:
    """A value outside the vocabulary is rejected, while ``unknown`` is accepted."""
    undecided = Key(key="pep_unknown_stage", kind="pep", fixed={"stage": "unknown"})
    LoadedSet(
        CONFIDENCE,
        "test",
        (_vendor(_entry("PEP", key="pep_unknown_stage", stage="unknown")),),
        DESCRIPTION,
        keys=(*KEYS, undecided),
    )
    with pytest.raises(ValueError, match="does not admit"):
        LoadedSet(CONFIDENCE, "test", (_vendor(_entry("PEP", kind="fdr")),), DESCRIPTION, keys=KEYS)


def test_a_software_version_is_reviewed_by_one_vendor_only() -> None:
    """One software version's level cannot be bound to two vendor entries of one set."""
    first = _vendor(_entry("PEP"))
    second = _vendor()
    with pytest.raises(ValueError, match="reviewed more than once"):
        LoadedSet(CONFIDENCE, "test", (first, second), DESCRIPTION, keys=KEYS)


def test_an_entry_id_repeats_nowhere_in_a_set() -> None:
    """Vendor and app entries share one id space, so a snapshot names each unambiguously."""
    later = RuleVariant(level="peptidoform_ion", software_version_pattern="^2\\.")
    first = _vendor(_entry("PEP"))
    second = _vendor(
        _entry("PEP").model_copy(update={"software_version_pattern": ("^2\\.",)}),
        variants=(later,),
    )
    with pytest.raises(ValueError, match="repeats"):
        LoadedSet(CONFIDENCE, "test", (first, second), DESCRIPTION, keys=KEYS)


def test_an_entry_id_names_where_its_field_lives() -> None:
    """``<source>/<version>/<level>/<attribute>/<key>/<column>``: a layer by its key, a varm
    column by table and column, obs columns by a prefix ending in ``*``."""
    assert entry_id("AlphaDIA/2.x/peptidoform_ion/layers/Precursor_Intensity/-") == EntryId(
        "AlphaDIA", "2.x", "peptidoform_ion", "layers", None, "Precursor_Intensity"
    )
    assert entry_id(
        "apb-fasta/*/peptidoform_ion/varm/fasta_validation/fasta_matches_contaminant"
    ) == EntryId(
        "apb-fasta", "*", "peptidoform_ion", "varm", "fasta_validation", "fasta_matches_contaminant"
    )
    assert entry_id("DIA-NN/2.x/peptidoform_fragment/var/-/Protein_Group").name == ("Protein_Group")
    assert entry_id("annotation:sdrf/*/peptidoform_ion/obs/-/factor_value_*").name == (
        "factor_value_*"
    )


@pytest.mark.parametrize(
    "text",
    [
        "DIA-NN/2.x/peptidoform_ion/layers/PEP",
        "DIA-NN/2.x/peptidoform_ion/obsm/X_pca/-",
        "DIA-NN/-/peptidoform_ion/layers/PEP/-",
        "*/2.x/peptidoform_ion/layers/PEP/-",
        "DIA-NN/2.x/peptidoform_ion/layers/-/PEP",
        "DIA-NN/2.x/peptidoform_ion/var/Q/Q_Value",
        "DIA-NN/2.x/peptidoform_ion/var/-/*",
    ],
)
def test_a_malformed_entry_id_is_refused(text: str) -> None:
    """Six fields, an AnnData attribute, a named source, version and level, and a key and column
    exactly where the attribute has them."""
    with pytest.raises(ValueError, match="entry id"):
        entry_id(text)


@pytest.mark.parametrize("name", sorted(packaged_descriptions()))
def test_every_packaged_entry_id_names_its_source_and_field(name: str) -> None:
    """A packaged entry's id names the source it belongs to and the field it reads."""
    for source in packaged_set(name).sources():
        for entry in source.entries:
            named = entry_id(entry.entry_id)
            assert (named.source, entry.source) == (source.label, source.label)
            assert (named.level, named.attribute, named.table) == (
                entry.reference.level,
                entry.reference.location,
                entry.reference.table,
            )


def test_a_bound_prefix_entry_takes_its_columns_id() -> None:
    """A prolfquapp ``group*`` entry bound to the column ``group_x`` names that column."""
    prefixed = next(
        entry
        for annotation in packaged_set("obs_annotation_alpha").annotations
        for entry in annotation.entries
        if entry.reference.prefix == "group"
    )
    bound = prefixed.bound("group_x")
    assert bound.entry_id == prefixed.entry_id.removesuffix("group*") + "group_x"
    assert bound.reference.name == "group_x"
    assert bound.source == prefixed.source == "annotation:prolfquapp"


def test_an_entry_of_every_level_takes_the_level_it_answers_on() -> None:
    """``annotation:prolfquapp/*/*/obs/-/group*`` is one entry for all five levels; on the
    protein level, bound to ``group_x``, it is that level's column."""
    assert entry_id("annotation:prolfquapp/*/*/obs/-/subject*").level == "*"
    every = next(
        entry
        for annotation in packaged_set("obs_annotation_alpha").annotations
        for entry in annotation.entries
        if entry.reference.prefix == "group"
    )
    assert every.entry_id == "annotation:prolfquapp/*/*/obs/-/group*"
    on_protein = every.on("protein")
    assert on_protein is not None
    bound = on_protein.bound("group_x")
    assert bound.entry_id == "annotation:prolfquapp/*/protein/obs/-/group_x"
    assert (bound.reference.level, bound.reference.name) == ("protein", "group_x")
    assert _entry("PEP").on("protein") is None, "an entry of one level answers only there"


def test_a_vendor_entry_names_its_level() -> None:
    """Rule levels come from vendor entries, so only apps and annotations name every level."""
    every = _entry("PEP").model_copy(
        update={"reference": Reference(level="*", location="layers", name="PEP")}
    )
    with pytest.raises(ValueError, match="a vendor entry names its level"):
        _vendor(every)


def _producer(*entries: SourceEntry, **overrides: object) -> ProducerEntries:
    fields: dict[str, object] = {
        "producer": "tool",
        "requires": ("tool", "provenance"),
        "instruction": "run `tool`",
        "entries": entries,
    } | overrides
    return ProducerEntries.model_validate(fields)


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


DOMAIN_SETS = tuple(name for name in packaged_descriptions() if name != "apb_alpha")
"""The sets that catalog the vendors' own columns; ``apb_alpha`` catalogs the columns APB2 writes."""


@pytest.mark.parametrize("name", DOMAIN_SETS)
def test_domain_sets_hold_no_apb2_columns(name: str) -> None:
    """APB2's canonical ProForma columns belong to the apb set, not to a domain set."""
    canonical = [
        entry.entry_id
        for vendor in _vendors(name)
        for entry in vendor.entries
        if (entry.reference.name or "").startswith("ProForma_")
    ]
    assert canonical == []


@pytest.mark.parametrize("name", DOMAIN_SETS)
def test_vendor_flags_answer_only_where_the_rule_reads_the_vendor(name: str) -> None:
    """A decoy or contaminant flag with no vendor input is false by declaration, not reported."""
    constant = [
        f"{entry.entry_id} under {pattern}"
        for vendor in _vendors(name)
        for entry in vendor.entries
        if entry.reference.name in ("apb_Decoy", "apb_Contaminant")
        for pattern in entry.software_version_pattern
        if not declared_var_column(
            rule_of(vendor.software_name, pattern, entry.reference.level),
            entry.reference.level,
            entry.reference.name,
        ).get("inputs")
    ]
    assert constant == []


def _apb_columns() -> set[tuple[str, str, str, str, str]]:
    """Every (software, pattern, level, column, kind) the apb set catalogs."""
    return {
        (vendor.software_name, pattern, entry.reference.level, name, entry.kind)
        for vendor in _vendors("apb_alpha")
        for entry in vendor.entries
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
