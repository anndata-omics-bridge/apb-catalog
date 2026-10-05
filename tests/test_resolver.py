"""The resolver answers only when exactly one reviewed entry fits, and says why otherwise."""

from __future__ import annotations

import pytest

from apb_catalog.resolver import (
    AbsentLevel,
    ConceptRequest,
    Resolution,
    ReviewedLevel,
    UnreviewedLevel,
)
from apb_catalog.source import (
    Evidence,
    Reference,
    Review,
    ReviewedRule,
    RuleVariant,
    SourceCatalogue,
    SourceEntry,
)
from apb_catalog.vocabulary import Qualifier, packaged_vocabulary

VARIANT = RuleVariant(rule="vendor/rules.json", level="ion", software_version_pattern="^1\\.")


def _entry(name: str, location: str = "layers", **qualifiers: str) -> SourceEntry:
    described = {"kind": "pep", "stage": "identification"} | qualifiers
    return SourceEntry.model_validate(
        {
            "entry_id": f"vendor.ion.{name}",
            "rules": ("vendor/rules.json",),
            "reference": {"level": "ion", "location": location, "name": name},
            "concept": "confidence",
            "qualifiers": described,
            "evidence": Evidence(basis="test"),
        }
    )


def _level(*entries: SourceEntry) -> ReviewedLevel:
    catalogue = SourceCatalogue(
        catalogue_id="vendor",
        catalogue_version="0.1",
        software_name="Vendor",
        review=Review(date="2026-09-30", apb2_revision="test"),
        variants=(VARIANT,),
        entries=entries,
    )
    return ReviewedLevel("ion", ReviewedRule(catalogue, VARIANT), entries)


def _request(location: str | None = "layers", **qualifiers: tuple[str, ...]) -> ConceptRequest:
    return ConceptRequest.model_validate(
        {"concept": "confidence", "level": "ion", "location": location, "qualifiers": qualifiers}
    )


def test_one_matching_entry_resolves_to_its_reference() -> None:
    """A single compatible, fully known entry is the answer."""
    resolution = _level(_entry("PEP"), _entry("Q_Value", kind="q_value")).resolve(
        _request(kind=("pep",), stage=("identification",))
    )
    assert resolution.status == "resolved"
    assert resolution.reference == Reference(level="ion", location="layers", name="PEP")


def test_pep_and_q_value_are_never_interchangeable() -> None:
    """Asking for a PEP never returns a q-value, even when it is the only confidence field."""
    resolution = _level(_entry("Q_Value", kind="q_value")).resolve(_request(kind=("pep",)))
    assert resolution.status == "missing"
    assert resolution.reference is None


def test_quantification_confidence_does_not_answer_an_identification_request() -> None:
    """An MS1-peak q-value is not an identification q-value."""
    level = _level(_entry("Peak_Q", kind="q_value", stage="quantification"))
    assert level.resolve(_request(kind=("q_value",), stage=("identification",))).status == "missing"
    assert level.resolve(_request(stage=("quantification",))).status == "resolved"


def test_two_matching_entries_are_ambiguous_and_both_are_reported() -> None:
    """The resolver never picks the first match."""
    level = _level(_entry("EG_Qvalue", kind="q_value"), _entry("FG_Qvalue", kind="q_value"))
    answer = level.resolve(_request(kind=("q_value",)))
    assert answer.status == "ambiguous"
    assert [candidate.reference.name for candidate in answer.candidates] == [
        "EG_Qvalue",
        "FG_Qvalue",
    ]


def test_an_unknown_qualifier_makes_the_answer_unknown() -> None:
    """An entry the reviewer could not place may match, so the resolver will not decide."""
    answer = _level(_entry("Q_Value", kind="q_value", stage="unknown")).resolve(
        _request(kind=("q_value",), stage=("identification",))
    )
    assert answer.status == "unknown"
    assert answer.candidates[0].undecided == ("stage",)
    assert answer.reasons == ("Q_Value leaves stage unknown",)


def test_accepting_unknown_admits_an_undecided_entry() -> None:
    """A consumer may explicitly accept an unestablished qualifier."""
    answer = _level(_entry("Q_Value", kind="q_value", stage="unknown")).resolve(
        _request(kind=("q_value",), stage=("identification", "unknown"))
    )
    assert answer.status == "resolved"


def test_an_undecided_entry_blocks_a_single_match() -> None:
    """One sure match plus one possible match is not a unique answer."""
    answer = _level(_entry("PEP"), _entry("Other_PEP", stage="unknown")).resolve(
        _request(kind=("pep",), stage=("identification",))
    )
    assert answer.status == "unknown"


def test_location_restricts_candidates() -> None:
    """A layer request ignores var columns with the same meaning."""
    level = _level(_entry("PEP", location="var"))
    assert level.resolve(_request(location="layers")).status == "missing"
    assert level.resolve(_request(location="var")).status == "resolved"


def test_an_unreviewed_level_answers_unknown_with_its_reason() -> None:
    """Without a reviewed rule no meaning can be asserted, not even absence."""
    answer = UnreviewedLevel("ion", "Vendor", "^1\\.", "never reviewed").resolve(_request())
    assert (answer.status, answer.reasons) == ("unknown", ("never reviewed",))
    assert UnreviewedLevel("ion", None, None, "none").entries == ()


def test_an_absent_level_answers_missing() -> None:
    """Asking about a level the result lacks is a missing answer."""
    assert AbsentLevel("peptide").resolve(_request()).status == "missing"


def test_a_resolution_carries_a_reference_exactly_when_resolved() -> None:
    """The stored record cannot claim an answer without a reference, or the reverse."""
    with pytest.raises(ValueError, match="exactly when it is resolved"):
        Resolution(request=_request(), status="resolved")
    with pytest.raises(ValueError, match="exactly when it is resolved"):
        Resolution(
            request=_request(),
            status="missing",
            reference=Reference(level="ion", location="layers", name="PEP"),
        )


def test_request_predicates_are_checked_against_the_vocabulary() -> None:
    """A request may name only declared qualifiers and admitted values."""
    concept = packaged_vocabulary().concept("confidence")
    concept.check_predicate({"kind": ("pep", "unknown")})
    with pytest.raises(ValueError, match="unknown qualifier"):
        concept.check_predicate({"flavour": ("pep",)})
    with pytest.raises(ValueError, match="does not admit"):
        concept.check_predicate({"kind": ("fdr",)})
    with pytest.raises(ValueError, match="accepts no value"):
        concept.check_predicate({"kind": ()})
    with pytest.raises(ValueError, match="unknown concept"):
        packaged_vocabulary().concept("abundance")


def test_unknown_is_a_reserved_qualifier_value() -> None:
    """The vocabulary cannot redefine ``unknown`` as an ordinary value."""
    with pytest.raises(ValueError, match="reserved"):
        Qualifier(definition="test", values={"unknown": "not allowed"})
