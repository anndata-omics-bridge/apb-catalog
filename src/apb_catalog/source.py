"""Reviewed meanings of retained APB fields, per vendor and effective-rule variant."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

from apb2.result_facade import ParsedLevelName
from pydantic import model_validator

from apb_catalog.vocabulary import FrozenModel, Vocabulary, packaged_vocabulary

type Location = Literal["layers", "var"]


class Reference(FrozenModel):
    """Where one retained field lives in an APB result, by its APB output name."""

    level: ParsedLevelName
    location: Location
    name: str


class Evidence(FrozenModel):
    """Why a reviewer assigned an entry's meaning."""

    basis: str
    source: str | None = None


class SourceEntry(FrozenModel):
    """The reviewed meaning of one retained field under the listed rule documents."""

    entry_id: str
    rules: tuple[str, ...]
    reference: Reference
    vendor_source: str
    concept: str
    qualifiers: dict[str, str]
    evidence: Evidence


class UnmappedField(FrozenModel):
    """A retained field a reviewer deliberately left without a catalogued meaning."""

    rules: tuple[str, ...]
    reference: Reference
    reason: str


class RuleVariant(FrozenModel):
    """One packaged rule level and the effective-rule fingerprints reviewed for it."""

    rule: str
    level: ParsedLevelName
    fingerprints: tuple[str, ...]


class Review(FrozenModel):
    """When a catalogue was reviewed and against which APB2 revision."""

    date: str
    apb2_revision: str


class SourceCatalogue(FrozenModel):
    """Every reviewed rule variant, entry and deliberate gap for one vendor."""

    catalogue_id: str
    catalogue_version: str
    software_name: str
    review: Review
    variants: tuple[RuleVariant, ...]
    entries: tuple[SourceEntry, ...]
    unmapped: tuple[UnmappedField, ...] = ()

    @model_validator(mode="after")
    def _consistent(self) -> SourceCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.catalogue_id}: duplicate entry ids")
        declared = {(variant.rule, variant.level) for variant in self.variants}
        if len(declared) != len(self.variants):
            raise ValueError(f"{self.catalogue_id}: duplicate rule variants")
        fields: list[SourceEntry | UnmappedField] = [*self.entries, *self.unmapped]
        for field in fields:
            if not field.rules:
                raise ValueError(f"{self.catalogue_id}: {field.reference} lists no rules")
            undeclared = {(rule, field.reference.level) for rule in field.rules} - declared
            if undeclared:
                raise ValueError(f"{self.catalogue_id}: {field.reference} uses {undeclared}")
        mapped = {(rule, entry.reference) for entry in self.entries for rule in entry.rules}
        gaps = {(rule, field.reference) for field in self.unmapped for rule in field.rules}
        if mapped & gaps:
            raise ValueError(
                f"{self.catalogue_id}: fields both mapped and unmapped: {mapped & gaps}"
            )
        return self

    def entries_for(self, variant: RuleVariant, /) -> tuple[SourceEntry, ...]:
        """Return the entries reviewed for one of this catalogue's rule variants."""
        return tuple(
            entry
            for entry in self.entries
            if variant.rule in entry.rules and entry.reference.level == variant.level
        )


@dataclass(frozen=True, slots=True)
class ReviewedRule:
    """The catalogue and rule variant an effective-rule fingerprint was reviewed as."""

    catalogue: SourceCatalogue
    variant: RuleVariant

    def entries(self) -> tuple[SourceEntry, ...]:
        """Return the entries reviewed for this rule variant."""
        return self.catalogue.entries_for(self.variant)


class SourceCatalogues:
    """Source catalogues checked against one vocabulary and indexed by rule fingerprint."""

    __slots__ = ("_by_fingerprint", "vocabulary")

    def __init__(self, vocabulary: Vocabulary, catalogues: tuple[SourceCatalogue, ...]) -> None:
        self.vocabulary = vocabulary
        self._by_fingerprint: dict[str, ReviewedRule] = {}
        for catalogue in catalogues:
            for entry in catalogue.entries:
                try:
                    vocabulary.concept(entry.concept).check_description(entry.qualifiers)
                except ValueError as error:
                    raise ValueError(f"{entry.entry_id}: {error}") from error
            for variant in catalogue.variants:
                for fingerprint in variant.fingerprints:
                    if fingerprint in self._by_fingerprint:
                        raise ValueError(f"fingerprint {fingerprint} is reviewed more than once")
                    self._by_fingerprint[fingerprint] = ReviewedRule(catalogue, variant)

    def reviewed(self, fingerprint: str, /) -> ReviewedRule | None:
        """Return the reviewed rule for a fingerprint, or ``None`` when it was never reviewed."""
        return self._by_fingerprint.get(fingerprint)


@cache
def packaged_catalogues() -> SourceCatalogues:
    """Load and cross-check the vocabulary and source catalogues shipped with this package."""
    directory = resources.files("apb_catalog").joinpath("data", "sources")
    catalogues = tuple(
        SourceCatalogue.model_validate_json(path.read_text("utf-8"))
        for path in sorted(directory.iterdir(), key=lambda path: path.name)
        if path.name.endswith(".json")
    )
    return SourceCatalogues(packaged_vocabulary(), catalogues)
