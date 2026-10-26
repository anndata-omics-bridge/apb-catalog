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

from pydantic import Field, TypeAdapter, model_validator

from apb_catalog.vocabulary import FrozenModel, SetVocabulary, packaged_vocabulary

type Location = Literal["obs", "layers", "var", "varm"]
type Address = tuple[Location, str | None, str]
type Requirement = Literal["MUST", "SHOULD", "MAY"]
type Convention = Literal["sdrf", "prolfquapp"]

READS: dict[Location, tuple[Location, ...]] = {
    "obs": ("obs",),
    "layers": ("layers",),
    "var": ("var", "varm"),
    "varm": ("varm",),
}
"""The locations a request reads: ``var`` and ``varm`` both hold one value per feature."""


class Reference(FrozenModel):
    """Where one field lives in an APB result: by its APB output name, its role or a prefix.

    A ``varm`` field also names its feature-aligned table. A ``var`` field may be named by the
    role the level's rule gives it, and an ``obs`` field of a sample annotation by the prefix of
    its column name; both are bound to the column a level holds before they answer.
    """

    level: str
    location: Location
    name: str | None = None
    table: str | None = None
    role: str | None = None
    prefix: str | None = None

    @model_validator(mode="after")
    def _one_way_to_name(self) -> Reference:
        if (self.location == "varm") != (self.table is not None):
            raise ValueError("a reference names a table exactly when it lives in varm")
        if sum(value is not None for value in (self.name, self.role, self.prefix)) != 1:
            raise ValueError("a reference gives exactly one of name, role or prefix")
        if self.role is not None and self.location != "var":
            raise ValueError("a role names a var column")
        if self.prefix is not None and self.location != "obs":
            raise ValueError("a prefix names an obs column")
        return self

    def address(self) -> Address:
        """The location, varm table and name a level's retained fields are indexed by."""
        if self.name is None:
            raise ValueError(f"{self} is not bound to a column")
        return (self.location, self.table, self.name)

    def bound(self, name: str, /) -> Reference:
        """This reference with the column it names on one level."""
        return Reference(level=self.level, location=self.location, name=name, table=self.table)


class Evidence(FrozenModel):
    """Why a reviewer assigned an entry's meaning."""

    basis: str
    source: str | None = None


class SourceEntry(FrozenModel):
    """The reviewed meaning of one retained field under the listed rule documents."""

    entry_id: str
    rules: tuple[str, ...]
    reference: Reference
    qualifiers: dict[str, str]
    evidence: Evidence

    def bound(self, name: str, /) -> SourceEntry:
        """This entry with its reference bound to one level's column."""
        return self.model_copy(update={"reference": self.reference.bound(name)})


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
            if entry.reference.name is None:
                raise ValueError(f"{self.catalogue_id}: a vendor entry names its column")
            undeclared = {(rule, entry.reference.level) for rule in entry.rules} - declared
            if undeclared:
                raise ValueError(f"{self.catalogue_id}: {entry.reference} uses {undeclared}")
        return self

    @property
    def label(self) -> str:
        """Who the entries come from: the vendor."""
        return self.software_name

    def entries_for(self, variant: RuleVariant, /) -> tuple[SourceEntry, ...]:
        """Return the entries reviewed for one of this catalogue's rule variants."""
        return tuple(
            entry
            for entry in self.entries
            if variant.rule in entry.rules and entry.reference.level == variant.level
        )


class ProducerCatalogue(FrozenModel):
    """Fields an APB producer, not the vendor, writes on every rule's level.

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
        if any(entry.reference.prefix is not None for entry in self.entries):
            raise ValueError(f"{self.catalogue_id}: prefixes belong to annotation catalogues")
        if bool(self.requires) != (self.instruction is not None):
            raise ValueError(f"{self.catalogue_id}: an instruction comes with a required run")
        return self

    @property
    def label(self) -> str:
        """Who the entries come from: ``producer:<name>``."""
        return f"producer:{self.producer}"

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


class AnnotationCatalogue(FrozenModel):
    """Sample-annotation fields of one annotation convention, found by column-name prefix.

    APB2 keeps an annotation's columns in each level's ``obs`` under sanitized header names and
    records the convention it read (``sdrf`` or ``prolfquapp``) in the result's metadata; the
    entries apply to a result whose metadata records this convention.
    """

    catalogue_id: str
    catalogue_version: str
    convention: Convention
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> AnnotationCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.catalogue_id}: duplicate entry ids")
        if any(entry.rules for entry in self.entries):
            raise ValueError(f"{self.catalogue_id}: annotation entries apply to every rule")
        if any(entry.reference.location != "obs" for entry in self.entries):
            raise ValueError(f"{self.catalogue_id}: annotation entries name obs columns")
        return self

    @property
    def label(self) -> str:
        """Who the entries come from: ``annotation:<convention>``."""
        return f"annotation:{self.convention}"

    def applies(self, metadata: Mapping[str, object], /) -> bool:
        """Whether a result's metadata records this catalogue's annotation convention."""
        return self.convention in metadata

    def entries_on(self, level: str) -> tuple[SourceEntry, ...]:
        """Return the entries this convention supplies on one level."""
        return tuple(entry for entry in self.entries if entry.reference.level == level)


class RequirementRow(FrozenModel):
    """How strongly a consumer needs one meaning on one level: a field location, a kind and
    the other qualifiers the field must carry."""

    level: str
    location: Location
    kind: str
    qualifiers: dict[str, str] = Field(default_factory=dict)
    requirement: Requirement

    def describes(self, entry: SourceEntry, /) -> bool:
        """Whether an entry on this row's level answers the row."""
        return (
            entry.reference.level == self.level
            and entry.reference.location in READS[self.location]
            and entry.qualifiers["kind"] == self.kind
            and all(entry.qualifiers.get(name) == value for name, value in self.qualifiers.items())
        )

    def asked(
        self, level: str, location: Location, qualifiers: Mapping[str, tuple[str, ...]]
    ) -> bool:
        """Whether a request on one level and location asks for this row's meaning."""
        return (
            level == self.level
            and location == self.location
            and qualifiers.get("kind") == (self.kind,)
            and all(qualifiers.get(name) == (value,) for name, value in self.qualifiers.items())
        )


type Requirements = tuple[RequirementRow, ...]


@dataclass(frozen=True, slots=True)
class ReviewedRule:
    """The catalogue and rule variant one software version's level was reviewed as."""

    catalogue: SourceCatalogue
    variant: RuleVariant

    def entries(self) -> tuple[SourceEntry, ...]:
        """Return the entries reviewed for this rule variant."""
        return self.catalogue.entries_for(self.variant)


class SourceCatalogues:
    """One set's source catalogues, checked against its vocabulary and indexed by software and
    version.

    ``producers`` hold the fields APB itself writes and ``annotations`` the sample-annotation
    fields; both apply to every level. A set made only of them has no vendor catalogue and needs
    no review. ``requirements`` are the consumer's requirement rows; a set without them is
    checked for coverage only.
    """

    __slots__ = (
        "_by_version",
        "annotations",
        "catalogues",
        "description",
        "producers",
        "requirements",
        "vocabulary",
        "vocabulary_version",
    )

    def __init__(
        self,
        vocabulary: SetVocabulary,
        vocabulary_version: str,
        catalogues: tuple[SourceCatalogue, ...],
        description: CatalogueDescription,
        producers: tuple[ProducerCatalogue, ...] = (),
        annotations: tuple[AnnotationCatalogue, ...] = (),
        requirements: Requirements = (),
    ) -> None:
        self.vocabulary = vocabulary
        self.vocabulary_version = vocabulary_version
        self.description = description
        self.catalogues = catalogues
        self.producers = producers
        self.annotations = annotations
        self.requirements = requirements
        self._by_version: dict[tuple[str, str, str], ReviewedRule] = {}
        entries = [entry for source in self.sources() for entry in source.entries]
        entry_ids = [entry.entry_id for entry in entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("an entry id repeats across the set's catalogues")
        for entry in entries:
            try:
                vocabulary.check_description(entry.qualifiers)
            except ValueError as error:
                raise ValueError(f"{entry.entry_id}: {error}") from error
        for row in requirements:
            try:
                vocabulary.check_predicate(
                    {
                        name: (value,)
                        for name, value in ({"kind": row.kind} | row.qualifiers).items()
                    }
                )
            except ValueError as error:
                raise ValueError(f"requirement on {row.level}: {error}") from error
        for catalogue in catalogues:
            for variant in catalogue.variants:
                key = (catalogue.software_name, variant.software_version_pattern, variant.level)
                if key in self._by_version:
                    raise ValueError(f"{' '.join(key)} is reviewed more than once")
                self._by_version[key] = ReviewedRule(catalogue, variant)

    def sources(self) -> tuple[SourceCatalogue | ProducerCatalogue | AnnotationCatalogue, ...]:
        """Every catalogue of the set: vendor, producer and annotation."""
        return (*self.catalogues, *self.producers, *self.annotations)

    @property
    def needs_review(self) -> bool:
        """Whether a level answers only once a vendor catalogue reviewed its rule."""
        return bool(self.catalogues)

    def reviewed(
        self, software_name: str, software_version_pattern: str, level: str
    ) -> ReviewedRule | None:
        """Return the rule reviewed for one software version's level, or ``None`` if none was."""
        return self._by_version.get((software_name, software_version_pattern, level))

    def requirement_for(
        self, level: str, location: Location, qualifiers: Mapping[str, tuple[str, ...]]
    ) -> RequirementRow | None:
        """Return the requirement row a request asks for, if any."""
        return next(
            (row for row in self.requirements if row.asked(level, location, qualifiers)), None
        )


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


_REQUIREMENTS = TypeAdapter(dict[str, tuple[RequirementRow, ...]])
_SET_REQUIREMENTS = TypeAdapter(tuple[RequirementRow, ...])


@cache
def packaged_requirements() -> dict[str, tuple[RequirementRow, ...]]:
    """Return the requirement rows of every packaged set that has them, by set name."""
    text = resources.files("apb_catalog").joinpath("data", "requirements.json").read_text("utf-8")
    requirements = _REQUIREMENTS.validate_json(text)
    unknown = sorted(set(requirements) - set(packaged_descriptions()))
    if unknown:
        raise ValueError(f"requirements for unknown catalogues {unknown}")
    return requirements


@cache
def packaged_catalogues(name: str, /) -> SourceCatalogues:
    """Load and cross-check one packaged catalogue set against its vocabulary."""
    descriptions = packaged_descriptions()
    if name not in descriptions:
        raise ValueError(f"unknown catalogue {name!r}; packaged: {list(descriptions)}")
    vocabularies = packaged_vocabulary()
    if name not in vocabularies.sets:
        raise ValueError(f"packaged catalogue {name!r} has no vocabulary")
    data = resources.files("apb_catalog").joinpath("data")
    return SourceCatalogues(
        vocabularies.sets[name],
        vocabularies.vocabulary_version,
        _read(data.joinpath("sources", name), SourceCatalogue),
        descriptions[name],
        _read(data.joinpath("producers", name), ProducerCatalogue),
        _read(data.joinpath("annotations", name), AnnotationCatalogue),
        packaged_requirements().get(name, ()),
    )


PLUGIN_GROUP = "apb_catalog.catalogues"
"""The entry-point group through which installed packages add catalogue sets."""


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
    """Load one plugin set with its own vocabulary."""
    folder = _plugin_folders()[name]
    requirements = folder.joinpath("requirements.json")
    return SourceCatalogues(
        SetVocabulary.model_validate_json(folder.joinpath("vocabulary.json").read_text("utf-8")),
        packaged_vocabulary().vocabulary_version,
        _read(folder.joinpath("sources"), SourceCatalogue),
        CatalogueDescription.model_validate_json(
            folder.joinpath("catalogue.json").read_text("utf-8")
        ),
        _read(folder.joinpath("producers"), ProducerCatalogue),
        _read(folder.joinpath("annotations"), AnnotationCatalogue),
        _SET_REQUIREMENTS.validate_json(requirements.read_text("utf-8"))
        if requirements.is_file()
        else (),
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
