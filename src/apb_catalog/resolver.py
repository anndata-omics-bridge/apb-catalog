"""Answer a request for a meaning from reviewed entries, without choosing silently."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, model_validator

from apb_catalog.source import READS, Location, Reference, Requirement, ReviewedRule, SourceEntry
from apb_catalog.vocabulary import UNKNOWN, FrozenModel

type ResolutionStatus = Literal["resolved", "missing", "ambiguous", "unknown"]


class FieldRequest(FrozenModel):
    """A consumer's question: one level, constrained by accepted qualifier values.

    Qualifiers left out accept any value. Accepting ``unknown`` admits entries whose reviewer
    could not establish that qualifier. A ``var`` request also reads feature-aligned ``varm``
    tables.
    """

    level: str
    location: Location | None = None
    qualifiers: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    def selects(self, entry: SourceEntry, /) -> bool:
        """Whether an entry answers at this level's location."""
        return self.location is None or entry.reference.location in READS[self.location]

    def admits(self, entry: SourceEntry) -> bool:
        """Whether an entry answers this request apart from qualifiers it leaves unknown."""
        return self.selects(entry) and not self.mismatched(entry.qualifiers)

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
    """The answer to one request; only ``resolved`` carries a reference.

    ``requirement`` records the requirement a missing field had when the lookup enforced it.
    """

    request: FieldRequest
    status: ResolutionStatus
    reference: Reference | None = None
    candidates: tuple[Candidate, ...] = ()
    reasons: tuple[str, ...] = ()
    requirement: Requirement | None = None

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
        names = ", ".join(str(candidate.reference.name) for candidate in resolution.candidates)
        super().__init__(
            f"{wanted} on {request.level} is {resolution.status}: "
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


class ProducedBinding(FrozenModel):
    """A level of a set without vendor catalogues: only APB's own fields answer."""

    status: Literal["produced"] = "produced"
    level: str
    software_name: str | None
    software_version_pattern: str | None


class UnreviewedBinding(FrozenModel):
    """A level no catalogue describes, and why."""

    status: Literal["unreviewed"] = "unreviewed"
    level: str
    software_name: str | None
    software_version_pattern: str | None
    reason: str


type LevelBinding = Annotated[
    ReviewedBinding | ProducedBinding | UnreviewedBinding, Field(discriminator="status")
]


@dataclass(frozen=True, slots=True)
class PendingEntry:
    """An entry whose producer has not run on the result yet, and why it cannot answer."""

    entry: SourceEntry
    reason: str


def _resolve(
    entries: tuple[SourceEntry, ...],
    pending: tuple[PendingEntry, ...],
    request: FieldRequest,
    missing: str,
) -> Resolution:
    """Resolve only when exactly one entry matches, none is undecided and none is pending."""
    compatible = [
        Candidate(
            entry_id=entry.entry_id,
            reference=entry.reference,
            qualifiers=entry.qualifiers,
            undecided=request.undecided(entry.qualifiers),
        )
        for entry in entries
        if request.admits(entry)
    ]
    waiting = [found for found in pending if request.admits(found.entry)]
    matches = [candidate for candidate in compatible if not candidate.undecided]
    undecided = [candidate for candidate in compatible if candidate.undecided]
    candidates = (
        *compatible,
        *(
            Candidate(
                entry_id=found.entry.entry_id,
                reference=found.entry.reference,
                qualifiers=found.entry.qualifiers,
            )
            for found in waiting
        ),
    )
    if len(matches) > 1:
        names = ", ".join(str(candidate.reference.name) for candidate in matches)
        return Resolution(
            request=request,
            status="ambiguous",
            candidates=candidates,
            reasons=(f"{len(matches)} entries match: {names}",),
        )
    if waiting:
        return Resolution(
            request=request,
            status="unknown",
            candidates=candidates,
            reasons=tuple(dict.fromkeys(found.reason for found in waiting)),
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
    return Resolution(request=request, status="missing", reasons=(missing,))


@dataclass(frozen=True, slots=True)
class ReviewedLevel:
    """A level with a reviewed rule; ``entries`` are those whose fields the level holds.

    ``pending`` entries belong to producers that have not run; a request they would answer is
    ``unknown`` until the producer runs.
    """

    level: str
    rule: ReviewedRule
    entries: tuple[SourceEntry, ...]
    pending: tuple[PendingEntry, ...] = ()

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
        )

    def resolve(self, request: FieldRequest, /) -> Resolution:
        """Resolve only when exactly one entry matches, none is undecided and none is pending."""
        missing = f"no reviewed {self.rule.variant.rule} entry on {self.level} matches"
        return _resolve(self.entries, self.pending, request, missing)


@dataclass(frozen=True, slots=True)
class ProducedLevel:
    """A level of a set without vendor catalogues, answered by APB's own fields alone."""

    level: str
    software_name: str | None
    software_version_pattern: str | None
    entries: tuple[SourceEntry, ...]
    pending: tuple[PendingEntry, ...] = ()

    def binding(self) -> ProducedBinding:
        """Describe the level's software and version; no review is involved."""
        return ProducedBinding(
            level=self.level,
            software_name=self.software_name,
            software_version_pattern=self.software_version_pattern,
        )

    def resolve(self, request: FieldRequest, /) -> Resolution:
        """Resolve only when exactly one entry matches, none is undecided and none is pending."""
        return _resolve(self.entries, self.pending, request, f"no entry on {self.level} matches")


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

    def resolve(self, request: FieldRequest, /) -> Resolution:
        """Report that no reviewed catalogue describes this level."""
        return Resolution(request=request, status="unknown", reasons=(self.reason,))


type LevelView = ReviewedLevel | ProducedLevel | UnreviewedLevel


@dataclass(frozen=True, slots=True)
class AbsentLevel:
    """A requested level the result does not contain."""

    level: str

    def resolve(self, request: FieldRequest, /) -> Resolution:
        """Report that the level itself is missing."""
        return Resolution(
            request=request,
            status="missing",
            reasons=(f"the result has no {self.level} level",),
        )
