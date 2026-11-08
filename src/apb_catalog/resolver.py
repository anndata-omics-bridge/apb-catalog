"""Answer a request for a meaning from reviewed entries, without choosing silently."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field, model_validator

from apb_catalog.rules import Location
from apb_catalog.source import READS, Reference, Requirement, ReviewedRule, SourceEntry
from apb_catalog.vocabulary import UNKNOWN, FrozenModel

type ResolutionStatus = Literal["resolved", "missing", "ambiguous", "unknown"]


class FieldRequest(FrozenModel):
    """A consumer's question: one level, constrained by a kind and accepted qualifier values.

    ``key`` names the access key asked for and ``kind`` the kind it stands for, ``None`` when the
    request spans every key; ``qualifiers`` hold the values the key fixes, plus any further
    qualifiers the caller asked for. Qualifiers left out accept any value. A request for a key
    answers with that key's entries; an entry of another key only keeps it undecided. An entry whose
    reviewer could not establish a qualifier is undecided unless the request accepts ``unknown``
    there. A ``var`` request also reads feature-aligned ``varm`` tables.
    """

    level: str
    location: Location | None = None
    key: str | None = None
    kind: str | None = None
    qualifiers: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    def wanted(self) -> str:
        """The key asked for, its kind and the qualifiers the request accepts, for messages."""
        kind = () if self.kind is None else (f"kind={self.kind}",)
        accepted = ", ".join(
            (*kind, *(f"{name}={'|'.join(values)}" for name, values in self.qualifiers.items()))
        )
        return accepted if self.key is None else f"{self.key} ({accepted})"

    def selects(self, entry: SourceEntry, /) -> bool:
        """Whether an entry answers at this level's location."""
        return self.location is None or entry.reference.location in READS[self.location]

    def admits(self, entry: SourceEntry) -> bool:
        """Whether an entry answers this request apart from qualifiers it leaves unknown: an
        entry of the key asked for, or of another key when it leaves unknown what the request
        asks."""
        return (
            self.selects(entry)
            and not self.mismatched(entry)
            and (self.key is None or entry.key == self.key or bool(self.undecided(entry)))
        )

    def mismatched(self, entry: SourceEntry, /) -> tuple[str, ...]:
        """Return what the request asks that an entry's kind or known values contradict."""
        kind = self.kind is not None and entry.kind != self.kind
        return (
            *(("kind",) if kind else ()),
            *(
                name
                for name, accepted in self.qualifiers.items()
                if entry.qualifiers[name] != UNKNOWN and entry.qualifiers[name] not in accepted
            ),
        )

    def undecided(self, entry: SourceEntry, /) -> tuple[str, ...]:
        """Return what the request asks that an entry leaves unknown: its qualifiers with the value
        ``unknown``. A kind is always known."""
        return tuple(
            name
            for name, accepted in self.qualifiers.items()
            if entry.qualifiers[name] == UNKNOWN and UNKNOWN not in accepted
        )


class Candidate(FrozenModel):
    """One entry compatible with a request, and the requested qualifiers it leaves unknown."""

    entry_id: str
    reference: Reference
    key: str
    kind: str
    qualifiers: dict[str, str]
    undecided: tuple[str, ...] = ()


class Resolution(FrozenModel):
    """The answer to one request; only ``resolved`` carries a reference.

    ``requirement`` records the requirement a missing field had when the catalog enforced it at
    init.
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

    def offered(self) -> tuple[str, ...]:
        """Return the distinct keys the candidates have, raising when the level is unreviewed."""
        if self.status == "unknown" and not self.candidates:
            raise UnresolvedField(self)
        return tuple(sorted({candidate.key for candidate in self.candidates}))

    def found(self) -> Reference | None:
        """Return the reference, ``None`` when the field is missing, and raise when undecidable."""
        if self.status in ("ambiguous", "unknown"):
            raise UnresolvedField(self)
        return self.reference


class UnresolvedField(LookupError):
    """A lookup the catalogue cannot answer with one field: ambiguous or unknown."""

    def __init__(self, resolution: Resolution) -> None:
        request = resolution.request
        names = ", ".join(str(candidate.reference.name) for candidate in resolution.candidates)
        super().__init__(
            f"{request.wanted()} on {request.level} is {resolution.status}: "
            f"{'; '.join(resolution.reasons)}" + (f"; candidates: {names}" if names else "")
        )
        self.resolution = resolution


class ReviewedBinding(FrozenModel):
    """A level whose rule's software and version match a reviewed catalogue variant."""

    status: Literal["reviewed"] = "reviewed"
    level: str
    software_name: str
    software_version_pattern: str


class ProducedBinding(FrozenModel):
    """A level of a set without vendor catalogues: only apps' and annotations' fields answer."""

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
            key=entry.key,
            kind=entry.kind,
            qualifiers=entry.qualifiers,
            undecided=request.undecided(entry),
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
                key=found.entry.key,
                kind=found.entry.kind,
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
            software_name=catalogue.software_name,
            software_version_pattern=self.rule.variant.software_version_pattern,
        )

    def resolve(self, request: FieldRequest, /) -> Resolution:
        """Resolve only when exactly one entry matches, none is undecided and none is pending."""
        variant = self.rule.variant
        missing = (
            f"no reviewed {self.rule.catalogue.software_name} {variant.software_version_pattern} "
            f"entry on {self.level} matches"
        )
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
