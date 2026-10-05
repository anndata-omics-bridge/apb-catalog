"""Answer a request for a meaning from reviewed entries, without choosing silently."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, model_validator

from apb_catalog.source import Location, Reference, Review, ReviewedRule, SourceEntry
from apb_catalog.vocabulary import UNKNOWN, FrozenModel

type ResolutionStatus = Literal["resolved", "missing", "ambiguous", "unknown"]


class ConceptRequest(FrozenModel):
    """A consumer's question: one concept on one level, constrained by accepted qualifier values.

    Qualifiers left out accept any value. Accepting ``unknown`` admits entries whose reviewer
    could not establish that qualifier.
    """

    concept: str
    level: str
    location: Location | None = None
    qualifiers: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    def selects(self, entry: SourceEntry, /) -> bool:
        """Whether an entry answers this concept at this level and location."""
        return entry.concept == self.concept and (
            self.location is None or entry.reference.location == self.location
        )

    def mismatched(self, qualifiers: Mapping[str, str], /) -> tuple[str, ...]:
        """Return the requested qualifiers an entry's known values contradict."""
        return tuple(
            name
            for name, accepted in self.qualifiers.items()
            if qualifiers[name] != UNKNOWN and qualifiers[name] not in accepted
        )

    def undecided(self, qualifiers: Mapping[str, str], /) -> tuple[str, ...]:
        """Return the requested qualifiers an entry leaves unknown."""
        return tuple(
            name
            for name, accepted in self.qualifiers.items()
            if qualifiers[name] == UNKNOWN and UNKNOWN not in accepted
        )


class Candidate(FrozenModel):
    """One entry compatible with a request, and the requested qualifiers it leaves unknown."""

    entry_id: str
    reference: Reference
    qualifiers: dict[str, str]
    undecided: tuple[str, ...] = ()


class Resolution(FrozenModel):
    """The answer to one request; only ``resolved`` carries a reference."""

    request: ConceptRequest
    status: ResolutionStatus
    reference: Reference | None = None
    candidates: tuple[Candidate, ...] = ()
    reasons: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _reference_iff_resolved(self) -> Resolution:
        if (self.status == "resolved") != (self.reference is not None):
            raise ValueError("a resolution carries a reference exactly when it is resolved")
        return self

    def offered(self, qualifier: str, /) -> tuple[str, ...]:
        """Return the distinct values the candidates carry, raising when the level is unreviewed."""
        if self.status == "unknown" and not self.candidates:
            raise UnresolvedField(self)
        return tuple(sorted({candidate.qualifiers[qualifier] for candidate in self.candidates}))

    def found(self) -> Reference | None:
        """Return the reference, ``None`` when the field is missing, and raise when undecidable."""
        if self.status in ("ambiguous", "unknown"):
            raise UnresolvedField(self)
        return self.reference


class UnresolvedField(LookupError):
    """A lookup the catalogue cannot answer with one field: ambiguous or unknown."""

    def __init__(self, resolution: Resolution) -> None:
        request = resolution.request
        wanted = ", ".join(
            f"{name}={'|'.join(values)}" for name, values in request.qualifiers.items()
        )
        names = ", ".join(candidate.reference.name for candidate in resolution.candidates)
        super().__init__(
            f"{request.concept} on {request.level} ({wanted}) is {resolution.status}: "
            f"{'; '.join(resolution.reasons)}" + (f"; candidates: {names}" if names else "")
        )
        self.resolution = resolution


class ReviewedBinding(FrozenModel):
    """A level whose rule's software and version match a reviewed catalogue variant."""

    status: Literal["reviewed"] = "reviewed"
    level: str
    catalogue_id: str
    catalogue_version: str
    software_name: str
    software_version_pattern: str
    rule: str
    review: Review


class UnreviewedBinding(FrozenModel):
    """A level no catalogue describes, and why."""

    status: Literal["unreviewed"] = "unreviewed"
    level: str
    software_name: str | None
    software_version_pattern: str | None
    reason: str


type LevelBinding = Annotated[ReviewedBinding | UnreviewedBinding, Field(discriminator="status")]


@dataclass(frozen=True, slots=True)
class ReviewedLevel:
    """A level with a reviewed rule; ``entries`` are those whose fields the result retains."""

    level: str
    rule: ReviewedRule
    entries: tuple[SourceEntry, ...]

    def binding(self) -> ReviewedBinding:
        """Describe how this level was bound to its catalogue."""
        catalogue = self.rule.catalogue
        return ReviewedBinding(
            level=self.level,
            catalogue_id=catalogue.catalogue_id,
            catalogue_version=catalogue.catalogue_version,
            software_name=catalogue.software_name,
            software_version_pattern=self.rule.variant.software_version_pattern,
            rule=self.rule.variant.rule,
            review=catalogue.review,
        )

    def resolve(self, request: ConceptRequest, /) -> Resolution:
        """Resolve only when exactly one entry matches and none is undecided."""
        compatible = [
            Candidate(
                entry_id=entry.entry_id,
                reference=entry.reference,
                qualifiers=entry.qualifiers,
                undecided=request.undecided(entry.qualifiers),
            )
            for entry in self.entries
            if request.selects(entry) and not request.mismatched(entry.qualifiers)
        ]
        matches = [candidate for candidate in compatible if not candidate.undecided]
        undecided = [candidate for candidate in compatible if candidate.undecided]
        candidates = tuple(compatible)
        if len(matches) > 1:
            names = ", ".join(candidate.reference.name for candidate in matches)
            return Resolution(
                request=request,
                status="ambiguous",
                candidates=candidates,
                reasons=(f"{len(matches)} entries match: {names}",),
            )
        if undecided:
            return Resolution(
                request=request,
                status="unknown",
                candidates=candidates,
                reasons=tuple(
                    f"{candidate.reference.name} leaves {', '.join(candidate.undecided)} unknown"
                    for candidate in undecided
                ),
            )
        if matches:
            return Resolution(
                request=request,
                status="resolved",
                reference=matches[0].reference,
                candidates=candidates,
            )
        return Resolution(
            request=request,
            status="missing",
            reasons=(f"no reviewed {self.rule.variant.rule} entry on {self.level} matches",),
        )


@dataclass(frozen=True, slots=True)
class UnreviewedLevel:
    """A level whose meanings cannot be established, so every answer is ``unknown``."""

    level: str
    software_name: str | None
    software_version_pattern: str | None
    reason: str

    @property
    def entries(self) -> tuple[SourceEntry, ...]:
        """An unreviewed level supplies no entries."""
        return ()

    def binding(self) -> UnreviewedBinding:
        """Describe why this level has no catalogue."""
        return UnreviewedBinding(
            level=self.level,
            software_name=self.software_name,
            software_version_pattern=self.software_version_pattern,
            reason=self.reason,
        )

    def resolve(self, request: ConceptRequest, /) -> Resolution:
        """Report that no reviewed catalogue describes this level."""
        return Resolution(request=request, status="unknown", reasons=(self.reason,))


@dataclass(frozen=True, slots=True)
class AbsentLevel:
    """A requested level the result does not contain."""

    level: str

    def resolve(self, request: ConceptRequest, /) -> Resolution:
        """Report that the level itself is missing."""
        return Resolution(
            request=request,
            status="missing",
            reasons=(f"the result has no {self.level} level",),
        )
