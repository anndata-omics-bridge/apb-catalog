"""Reviewed meanings of retained APB fields, per vendor and effective-rule variant."""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.metadata import EntryPoints, entry_points
from importlib.resources.abc import Traversable
from typing import Literal, TypedDict, cast

from pydantic import Field, TypeAdapter, model_validator

from apb_catalog.rules import Address, Location, rule_levels
from apb_catalog.vocabulary import FrozenModel, Qualifier, SetVocabulary

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

    software_name: str
    variants: tuple[RuleVariant, ...]
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> SourceCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.software_name}: duplicate entry ids")
        declared = {(variant.rule, variant.level) for variant in self.variants}
        if len(declared) != len(self.variants):
            raise ValueError(f"{self.software_name}: duplicate rule variants")
        for entry in self.entries:
            if not entry.rules:
                raise ValueError(f"{self.software_name}: {entry.reference} lists no rules")
            if entry.reference.name is None:
                raise ValueError(f"{self.software_name}: a vendor entry names its column")
            undeclared = {(rule, entry.reference.level) for rule in entry.rules} - declared
            if undeclared:
                raise ValueError(f"{self.software_name}: {entry.reference} uses {undeclared}")
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

    producer: str
    requires: tuple[str, ...] = ()
    instruction: str | None = None
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> ProducerCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.label}: duplicate entry ids")
        if any(entry.rules for entry in self.entries):
            raise ValueError(f"{self.label}: producer entries apply to every rule")
        if any(entry.reference.prefix is not None for entry in self.entries):
            raise ValueError(f"{self.label}: prefixes belong to annotation catalogues")
        if bool(self.requires) != (self.instruction is not None):
            raise ValueError(f"{self.label}: an instruction comes with a required run")
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

    convention: Convention
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> AnnotationCatalogue:
        entry_ids = [entry.entry_id for entry in self.entries]
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError(f"{self.label}: duplicate entry ids")
        if any(entry.rules for entry in self.entries):
            raise ValueError(f"{self.label}: annotation entries apply to every rule")
        if any(entry.reference.location != "obs" for entry in self.entries):
            raise ValueError(f"{self.label}: annotation entries name obs columns")
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


TABLES = ("entries", "entry_qualifiers", "vocabulary", "requirements", "producers")
"""The CSV tables a catalogue folder holds, each named ``<table>.csv``; ``datapackage.json``
declares their columns."""

type Row = dict[str, str]


class _Field(TypedDict):
    name: str


class _Schema(TypedDict):
    fields: list[_Field]
    primaryKey: list[str]


class _Resource(TypedDict):
    name: str
    schema: _Schema


class _DataPackage(TypedDict):
    version: str
    resources: list[_Resource]


def _data() -> Traversable:
    return resources.files("apb_catalog").joinpath("data")


@cache
def _datapackage() -> _DataPackage:
    text = _data().joinpath("datapackage.json").read_text("utf-8")
    return TypeAdapter(_DataPackage).validate_json(text)


def catalog_version() -> str:
    """The version of the catalogue tables, as ``datapackage.json`` records it."""
    return _datapackage()["version"]


@cache
def _schemas() -> dict[str, _Schema]:
    return {resource["name"]: resource["schema"] for resource in _datapackage()["resources"]}


def _table(folder: Traversable, table: str, /) -> tuple[Row, ...]:
    """Every row of one table in a folder; none when the folder has no such file.

    Raises:
        ValueError: The header differs from the columns ``datapackage.json`` declares, or two
            rows share a primary key.
    """
    path = folder.joinpath(f"{table}.csv")
    if not path.is_file():
        return ()
    schema = _schemas()[table]
    reader = csv.DictReader(io.StringIO(path.read_text("utf-8")))
    columns = [found["name"] for found in schema["fields"]]
    if reader.fieldnames != columns:
        raise ValueError(f"{table}.csv has the columns {reader.fieldnames}, not {columns}")
    rows = tuple(reader)
    keys = Counter(tuple(row[name] for name in schema["primaryKey"]) for row in rows)
    repeated = sorted(key for key, count in keys.items() if count > 1)
    if repeated:
        raise ValueError(f"{table}.csv repeats the keys {repeated}")
    return rows


def _set_names(folder: Traversable, /) -> list[str]:
    """The sets a folder describes, in table order, after checking every row names one of them.

    Raises:
        ValueError: A table has rows of a set that ``vocabulary.csv`` does not describe.
    """
    names = [row["set"] for row in _table(folder, "vocabulary") if not row["qualifier"]]
    for table in TABLES:
        stray = sorted({row["set"] for row in _table(folder, table)} - set(names))
        if stray:
            raise ValueError(f"{table}.csv has rows of undescribed sets {stray}")
    return names


def _load(folder: Traversable, name: str, /) -> SourceCatalogues:
    """Load one set's rows from a folder of catalogue tables and check them.

    Vendor entries name their software in ``source``; such a set reviews every rule level of
    APB2's packaged rules. ``producer:<name>`` and ``annotation:<convention>`` entries apply to
    every rule.
    """

    def rows(table: str) -> list[Row]:
        return [row for row in _table(folder, table) if row["set"] == name]

    description, vocabulary = _vocabulary(name, rows("vocabulary"))
    qualifiers: dict[str, dict[str, str]] = {}
    for row in rows("entry_qualifiers"):
        qualifiers.setdefault(row["entry_id"], {})[row["qualifier"]] = row["value"]
    by_source: dict[str, list[SourceEntry]] = {}
    for row in rows("entries"):
        entry = _entry(row, qualifiers.pop(row["entry_id"], {}))
        by_source.setdefault(row["source"], []).append(entry)
    if qualifiers:
        raise ValueError(f"{name}: entry_qualifiers.csv qualifies no entry {sorted(qualifiers)}")
    runs = {row["producer"]: row for row in rows("producers")}
    vendors: dict[str, tuple[SourceEntry, ...]] = {}
    producers: list[ProducerCatalogue] = []
    annotations: list[AnnotationCatalogue] = []
    for source, entries in by_source.items():
        prefix, _, named = source.partition(":")
        if prefix == "producer":
            run = runs.pop(named, None)
            producers.append(
                ProducerCatalogue(
                    producer=named,
                    requires=() if run is None else tuple(run["requires"].split(".")),
                    instruction=None if run is None else run["instruction"],
                    entries=tuple(entries),
                )
            )
        elif prefix == "annotation":
            annotations.append(
                AnnotationCatalogue.model_validate({"convention": named, "entries": entries})
            )
        else:
            vendors[source] = tuple(entries)
    if runs:
        raise ValueError(f"{name}: producers.csv names producers without entries {sorted(runs)}")
    return SourceCatalogues(
        vocabulary,
        catalog_version(),
        _vendors(name, vendors),
        description,
        tuple(producers),
        tuple(annotations),
        tuple(
            RequirementRow.model_validate(
                {key: value for key, value in row.items() if key != "set"}
            )
            for row in rows("requirements")
        ),
    )


def _vocabulary(name: str, rows: Sequence[Row]) -> tuple[CatalogueDescription, SetVocabulary]:
    """A set's description and vocabulary from its rows: the set's, each qualifier's, and each
    value's."""
    heads = [row for row in rows if not row["qualifier"]]
    if len(heads) != 1:
        raise ValueError(f"vocabulary.csv has {len(heads)} rows describing the set {name!r}")
    head = heads[0]
    definitions = {
        row["qualifier"]: row["definition"] for row in rows if row["qualifier"] and not row["value"]
    }
    values: dict[str, dict[str, str]] = {qualifier: {} for qualifier in definitions}
    for row in rows:
        if row["value"]:
            if row["qualifier"] not in values:
                raise ValueError(f"{name}: vocabulary.csv defines {row['value']!r} of no qualifier")
            values[row["qualifier"]][row["value"]] = row["definition"]
    description = CatalogueDescription(
        purpose=head["purpose"], used_by=tuple(head["used_by"].split(";"))
    )
    vocabulary = SetVocabulary(
        definition=head["definition"],
        qualifiers={
            qualifier: Qualifier(definition=definition, values=values[qualifier])
            for qualifier, definition in definitions.items()
        },
    )
    return description, vocabulary


def _entry(row: Row, qualifiers: Mapping[str, str]) -> SourceEntry:
    """One entry from its ``entries.csv`` row and its other qualifiers."""
    if row["reference_by"] not in ("name", "role", "prefix"):
        raise ValueError(f"{row['entry_id']}: reference_by is name, role or prefix")
    reference = Reference.model_validate(
        {
            "level": row["level"],
            "location": row["location"],
            "table": row["table"] or None,
            row["reference_by"]: row["reference"],
        }
    )
    return SourceEntry(
        entry_id=row["entry_id"],
        rules=tuple(row["rules"].split(";")) if row["rules"] else (),
        reference=reference,
        qualifiers={"kind": row["kind"], **qualifiers},
        evidence=Evidence(basis=row["basis"], source=row["evidence_url"] or None),
    )


def _vendors(
    name: str, entries: Mapping[str, tuple[SourceEntry, ...]]
) -> tuple[SourceCatalogue, ...]:
    """One catalogue per software of APB2's packaged rules, each reviewing every rule level of
    that software, when the set has vendor entries; none otherwise."""
    if not entries:
        return ()
    variants: dict[str, list[RuleVariant]] = {}
    for found in rule_levels():
        variants.setdefault(found.software_name, []).append(
            RuleVariant(
                rule=found.rule,
                level=found.level,
                software_version_pattern=found.software_version_pattern,
            )
        )
    unknown = sorted(set(entries) - set(variants))
    if unknown:
        raise ValueError(f"{name}: no packaged rule declares the software {unknown}")
    return tuple(
        SourceCatalogue(
            software_name=software, variants=tuple(found), entries=entries.get(software, ())
        )
        for software, found in variants.items()
    )


@cache
def packaged_descriptions() -> dict[str, CatalogueDescription]:
    """Return every packaged catalogue set's description, by set name."""
    rows = _table(_data(), "vocabulary")
    return {
        name: _vocabulary(name, [row for row in rows if row["set"] == name])[0]
        for name in _set_names(_data())
    }


@cache
def packaged_catalogues(name: str, /) -> SourceCatalogues:
    """Load and cross-check one packaged catalogue set against its vocabulary."""
    descriptions = packaged_descriptions()
    if name not in descriptions:
        raise ValueError(f"unknown catalogue {name!r}; packaged: {list(descriptions)}")
    return _load(_data(), name)


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
    """Load one plugin set, whose folder holds the tables of that set alone.

    Raises:
        ValueError: The folder describes another set.
    """
    folder = _plugin_folders()[name]
    described = _set_names(folder)
    if described != [name]:
        raise ValueError(f"the plugin folder of {name!r} describes the sets {described}")
    return _load(folder, name)
