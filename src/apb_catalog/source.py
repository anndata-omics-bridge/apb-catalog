"""Reviewed meanings of retained APB fields, per vendor and effective-rule variant."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

from pydantic import model_validator

from apb_catalog.vocabulary import FrozenModel, Vocabulary, packaged_vocabulary

type Location = Literal["layers", "var"]


class Reference(FrozenModel):
    """Where one retained field lives in an APB result, by its APB output name."""

    level: str
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
    concept: str
    qualifiers: dict[str, str]
    evidence: Evidence


class RuleVariant(FrozenModel):
    """One packaged rule level, bound by the software version pattern its rule declares."""

    rule: str
    level: str
    software_version_pattern: str


class Review(FrozenModel):
    """When a catalogue was reviewed and against which APB2 revision."""

    date: str
    apb2_revision: str


class SourceCatalogue(FrozenModel):
    """Every reviewed rule variant of one vendor and the entries one consumer needs from it."""

    catalogue_id: str
    catalogue_version: str
    software_name: str
    review: Review
    variants: tuple[RuleVariant, ...]
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> SourceCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.catalogue_id}: duplicate entry ids")
        declared = {(variant.rule, variant.level) for variant in self.variants}
        if len(declared) != len(self.variants):
            raise ValueError(f"{self.catalogue_id}: duplicate rule variants")
        for entry in self.entries:
            if not entry.rules:
                raise ValueError(f"{self.catalogue_id}: {entry.reference} lists no rules")
            undeclared = {(rule, entry.reference.level) for rule in entry.rules} - declared
            if undeclared:
                raise ValueError(f"{self.catalogue_id}: {entry.reference} uses {undeclared}")
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
    """The catalogue and rule variant one software version's level was reviewed as."""

    catalogue: SourceCatalogue
    variant: RuleVariant

    def entries(self) -> tuple[SourceEntry, ...]:
        """Return the entries reviewed for this rule variant."""
        return self.catalogue.entries_for(self.variant)


class SourceCatalogues:
    """Source catalogues checked against one vocabulary and indexed by software and version."""

    __slots__ = ("_by_version", "description", "vocabulary")

    def __init__(
        self,
        vocabulary: Vocabulary,
        catalogues: tuple[SourceCatalogue, ...],
        description: CatalogueDescription,
    ) -> None:
        self.vocabulary = vocabulary
        self.description = description
        self._by_version: dict[tuple[str, str, str], ReviewedRule] = {}
        for catalogue in catalogues:
            for entry in catalogue.entries:
                try:
                    vocabulary.concept(entry.concept).check_description(entry.qualifiers)
                except ValueError as error:
                    raise ValueError(f"{entry.entry_id}: {error}") from error
            for variant in catalogue.variants:
                key = (catalogue.software_name, variant.software_version_pattern, variant.level)
                if key in self._by_version:
                    raise ValueError(f"{' '.join(key)} is reviewed more than once")
                self._by_version[key] = ReviewedRule(catalogue, variant)

    def reviewed(
        self, software_name: str, software_version_pattern: str, level: str
    ) -> ReviewedRule | None:
        """Return the rule reviewed for one software version's level, or ``None`` if none was."""
        return self._by_version.get((software_name, software_version_pattern, level))


class CatalogueDescription(FrozenModel):
    """What one catalogue set holds and who uses it."""

    purpose: str
    used_by: tuple[str, ...]


@cache
def packaged_descriptions() -> dict[str, CatalogueDescription]:
    """Return every packaged catalogue set's description, by set name."""
    text = resources.files("apb_catalog").joinpath("data", "catalogues.json").read_text("utf-8")
    return {
        name: CatalogueDescription.model_validate(description)
        for name, description in json.loads(text).items()
    }


@cache
def packaged_catalogues(name: str, /) -> SourceCatalogues:
    """Load and cross-check one packaged catalogue set against the shared vocabulary."""
    descriptions = packaged_descriptions()
    if name not in descriptions:
        raise ValueError(f"unknown catalogue {name!r}; packaged: {list(descriptions)}")
    directory = resources.files("apb_catalog").joinpath("data", "sources", name)
    catalogues = tuple(
        SourceCatalogue.model_validate_json(path.read_text("utf-8"))
        for path in sorted(directory.iterdir(), key=lambda path: path.name)
        if path.name.endswith(".json")
    )
    return SourceCatalogues(packaged_vocabulary(), catalogues, descriptions[name])
