"""Reviewed meanings of retained APB fields, per vendor and effective-rule variant."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.metadata import EntryPoints, entry_points
from importlib.resources.abc import Traversable
from typing import Literal, cast

from pydantic import TypeAdapter, model_validator

from apb_catalog.vocabulary import Concept, FrozenModel, Vocabulary, packaged_vocabulary

type Location = Literal["layers", "var", "varm"]
type Address = tuple[Location, str | None, str]
type Requirement = Literal["MUST", "SHOULD", "MAY"]
type Requirements = Mapping[str, Mapping[str, Requirement]]
"""The requirement level of each kind, per level, that a consumer's schema sets."""


class Reference(FrozenModel):
    """Where one retained field lives in an APB result, by its APB output name.

    A ``varm`` field also names its feature-aligned table.
    """

    level: str
    location: Location
    name: str
    table: str | None = None

    @model_validator(mode="after")
    def _table_iff_varm(self) -> Reference:
        if (self.location == "varm") != (self.table is not None):
            raise ValueError("a reference names a table exactly when it lives in varm")
        return self

    def address(self) -> Address:
        """The location, varm table and name a level's retained fields are indexed by."""
        return (self.location, self.table, self.name)


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


class SourceCatalogue(FrozenModel):
    """Every reviewed rule variant of one vendor and the entries one consumer needs from it."""

    catalogue_id: str
    catalogue_version: str
    software_name: str
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


class ProducerCatalogue(FrozenModel):
    """Fields an APB producer, not the vendor, writes on every reviewed rule's level.

    ``requires`` is the metadata path that records the producer's run; conversion's own columns
    need none. Until a required run is recorded, its entries are pending and ``instruction``
    says what to run.
    """

    catalogue_id: str
    catalogue_version: str
    producer: str
    requires: tuple[str, ...] = ()
    instruction: str | None = None
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> ProducerCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.catalogue_id}: duplicate entry ids")
        if any(entry.rules for entry in self.entries):
            raise ValueError(f"{self.catalogue_id}: producer entries apply to every rule")
        if bool(self.requires) != (self.instruction is not None):
            raise ValueError(f"{self.catalogue_id}: an instruction comes with a required run")
        return self

    def entries_on(self, level: str) -> tuple[SourceEntry, ...]:
        """Return the entries this producer supplies on one level."""
        return tuple(entry for entry in self.entries if entry.reference.level == level)

    def ran(self, metadata: Mapping[str, object]) -> bool:
        """Whether a result's metadata records this producer's run."""
        section: Mapping[str, object] = metadata
        for depth, key in enumerate(self.requires):
            if key not in section:
                return False
            if depth == len(self.requires) - 1:
                break
            child = section[key]
            if not isinstance(child, dict):
                return False
            section = cast(dict[str, object], child)
        return True

    def pending_reason(self) -> str:
        """Why an entry of this producer cannot answer yet, and what to run."""
        return f"{self.producer} has not run on this result; {self.instruction}"


@dataclass(frozen=True, slots=True)
class ReviewedRule:
    """The catalogue and rule variant one software version's level was reviewed as."""

    catalogue: SourceCatalogue
    variant: RuleVariant

    def entries(self) -> tuple[SourceEntry, ...]:
        """Return the entries reviewed for this rule variant."""
        return self.catalogue.entries_for(self.variant)


class SourceCatalogues:
    """Source catalogues checked against one vocabulary and indexed by software and version.

    ``producers`` hold the fields APB itself writes; they apply to every reviewed level.
    ``requirements`` are the consumer schema's requirement levels per level and kind; a set
    without them is checked for coverage only.
    """

    __slots__ = (
        "_by_version",
        "catalogues",
        "description",
        "producers",
        "requirements",
        "vocabulary",
    )

    def __init__(
        self,
        vocabulary: Vocabulary,
        catalogues: tuple[SourceCatalogue, ...],
        description: CatalogueDescription,
        producers: tuple[ProducerCatalogue, ...] = (),
        requirements: Requirements | None = None,
    ) -> None:
        self.vocabulary = vocabulary
        self.description = description
        self.catalogues = catalogues
        self.producers = producers
        self.requirements: Requirements = requirements or {}
        self._by_version: dict[tuple[str, str, str], ReviewedRule] = {}
        entries = [entry for source in (*catalogues, *producers) for entry in source.entries]
        entry_ids = [entry.entry_id for entry in entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("an entry id repeats across the set's catalogues")
        for entry in entries:
            try:
                vocabulary.concept(entry.concept).check_description(entry.qualifiers)
            except ValueError as error:
                raise ValueError(f"{entry.entry_id}: {error}") from error
        kinds = {
            kind
            for concept in {entry.concept for entry in entries}
            for kind in vocabulary.concept(concept).qualifiers["kind"].values
        }
        for level, required in self.requirements.items():
            unknown = sorted(set(required) - kinds)
            if unknown:
                raise ValueError(f"requirements on {level} name unknown kinds {unknown}")
        for catalogue in catalogues:
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


_REQUIREMENTS = TypeAdapter(dict[str, dict[str, dict[str, Requirement]]])


@cache
def packaged_requirements() -> dict[str, dict[str, dict[str, Requirement]]]:
    """Return the requirement levels of every packaged set that has them, by set name."""
    text = resources.files("apb_catalog").joinpath("data", "requirements.json").read_text("utf-8")
    requirements = _REQUIREMENTS.validate_json(text)
    unknown = sorted(set(requirements) - set(packaged_descriptions()))
    if unknown:
        raise ValueError(f"requirements for unknown catalogues {unknown}")
    return requirements


@cache
def packaged_catalogues(name: str, /) -> SourceCatalogues:
    """Load and cross-check one packaged catalogue set against the shared vocabulary."""
    descriptions = packaged_descriptions()
    if name not in descriptions:
        raise ValueError(f"unknown catalogue {name!r}; packaged: {list(descriptions)}")
    data = resources.files("apb_catalog").joinpath("data")
    return SourceCatalogues(
        packaged_vocabulary(),
        _read(data.joinpath("sources", name), SourceCatalogue),
        descriptions[name],
        _read(data.joinpath("producers", name), ProducerCatalogue),
        packaged_requirements().get(name),
    )


PLUGIN_GROUP = "apb_catalog.catalogues"
"""The entry-point group through which installed packages add catalogue sets."""


class VocabularyExtension(FrozenModel):
    """The concepts a plugin set adds to the packaged vocabulary."""

    concepts: dict[str, Concept]


_LEVEL_REQUIREMENTS = TypeAdapter(dict[str, dict[str, Requirement]])


def plugin_folders(points: EntryPoints) -> dict[str, Traversable]:
    """The catalogue set folder each entry point names, by set name.

    Raises:
        ValueError: Two entry points name one set.
    """
    repeated = sorted(
        name for name, count in Counter(point.name for point in points).items() if count > 1
    )
    if repeated:
        raise ValueError(f"several installed plugins name the catalogue sets {repeated}")
    return {point.name: resources.files(point.value) for point in points}


@cache
def _plugin_folders() -> dict[str, Traversable]:
    """Every installed plugin's catalogue set folder, by set name."""
    return plugin_folders(entry_points(group=PLUGIN_GROUP))


def catalogue_descriptions() -> dict[str, CatalogueDescription]:
    """Return every packaged and plugin catalogue set's description, by set name.

    Raises:
        ValueError: A plugin set has a packaged set's name.
    """
    packaged = packaged_descriptions()
    plugins = _plugin_folders()
    clashing = sorted(set(packaged) & set(plugins))
    if clashing:
        raise ValueError(f"plugin catalogue sets {clashing} have the names of packaged sets")
    return {**packaged, **{name: _plugin_set(name).description for name in plugins}}


def catalogue_set(name: str, /) -> SourceCatalogues:
    """Load one packaged or plugin catalogue set.

    Raises:
        ValueError: No packaged or plugin set has this name.
    """
    descriptions = catalogue_descriptions()
    if name not in descriptions:
        raise ValueError(
            f"unknown catalogue {name!r}; packaged: {list(packaged_descriptions())}, "
            f"plugins: {list(_plugin_folders())}"
        )
    return packaged_catalogues(name) if name in packaged_descriptions() else _plugin_set(name)


@cache
def _plugin_set(name: str, /) -> SourceCatalogues:
    """Load one plugin set, its concepts added to the packaged vocabulary."""
    folder = _plugin_folders()[name]
    packaged = packaged_vocabulary()
    added = VocabularyExtension.model_validate_json(
        folder.joinpath("vocabulary.json").read_text("utf-8")
    )
    redefined = sorted(set(added.concepts) & set(packaged.concepts))
    if redefined:
        raise ValueError(f"plugin catalogue set {name!r} redefines packaged concepts {redefined}")
    vocabulary = Vocabulary(
        vocabulary_version=packaged.vocabulary_version,
        concepts={**packaged.concepts, **added.concepts},
    )
    requirements = folder.joinpath("requirements.json")
    return SourceCatalogues(
        vocabulary,
        _read(folder.joinpath("sources"), SourceCatalogue),
        CatalogueDescription.model_validate_json(
            folder.joinpath("catalogue.json").read_text("utf-8")
        ),
        _read(folder.joinpath("producers"), ProducerCatalogue),
        _LEVEL_REQUIREMENTS.validate_json(requirements.read_text("utf-8"))
        if requirements.is_file()
        else None,
    )


def _read[T: FrozenModel](directory: Traversable, model: type[T]) -> tuple[T, ...]:
    """Every JSON file of one directory, by file name; none when the directory is absent."""
    if not directory.is_dir():
        return ()
    return tuple(
        model.model_validate_json(path.read_text("utf-8"))
        for path in sorted(directory.iterdir(), key=lambda path: path.name)
        if path.name.endswith(".json")
    )
