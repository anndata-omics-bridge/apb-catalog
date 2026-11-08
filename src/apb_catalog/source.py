"""Reviewed meanings of retained APB fields, per vendor and software version."""

from __future__ import annotations

import csv
import io
import logging
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from importlib import resources
from importlib.metadata import EntryPoints, entry_points
from importlib.resources.abc import Traversable
from typing import Literal, TypedDict, cast

from pydantic import Field, TypeAdapter, model_validator

from apb_catalog.rules import (
    ANY,
    Address,
    EntryId,
    Location,
    entry_id,
    rule_levels,
    version_patterns,
)
from apb_catalog.vocabulary import FrozenModel, Qualifier, SetVocabulary

type Requirement = Literal["required", "recommended", "optional"]
type Convention = Literal["sdrf", "prolfquapp"]

logger = logging.getLogger(__name__)

READS: dict[Location, tuple[Location, ...]] = {
    "obs": ("obs",),
    "layers": ("layers",),
    "var": ("var", "varm"),
    "varm": ("varm",),
}
"""The locations a request reads: ``var`` and ``varm`` both hold one value per feature."""


class Reference(FrozenModel):
    """Where one field lives in an APB result: by its APB output name or a prefix.

    A ``varm`` field also names its feature-aligned table. An ``obs`` field of a sample
    annotation is named by the prefix of its column name and bound to the column a level holds
    before it answers.
    """

    level: str
    location: Location
    name: str | None = None
    table: str | None = None
    prefix: str | None = None

    @model_validator(mode="after")
    def _one_way_to_name(self) -> Reference:
        if (self.location == "varm") != (self.table is not None):
            raise ValueError("a reference names a table exactly when it lives in varm")
        if (self.name is None) == (self.prefix is None):
            raise ValueError("a reference gives exactly one of name or prefix")
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
    """The reviewed meaning of one retained field for the listed software version patterns.

    ``key`` is the access key the entry names; ``kind`` is that key's kind, and ``qualifiers``
    hold the entry's value for every other qualifier of the set, the key's fixed value included.
    """

    entry_id: str
    software_version_pattern: tuple[str, ...]
    reference: Reference
    key: str
    kind: str
    qualifiers: dict[str, str]
    evidence: Evidence

    @property
    def source(self) -> str:
        """Who the entry comes from: the software, an app, or ``annotation:<convention>``, the
        first field of its id ``<source>/<version>/<level>/<attribute>/<key>/<column>``; one id
        with two kinds is two entries."""
        return self.entry_id.partition("/")[0]

    def on(self, level: str, /) -> SourceEntry | None:
        """This entry on one level: itself, an entry of every level (``*``) taking that level in
        its reference and id, or ``None`` on another level."""
        if self.reference.level == level:
            return self
        if self.reference.level != ANY:
            return None
        source, version, _, rest = self.entry_id.split("/", 3)
        return self.model_copy(
            update={
                "entry_id": f"{source}/{version}/{level}/{rest}",
                "reference": self.reference.model_copy(update={"level": level}),
            }
        )

    def bound(self, name: str, /) -> SourceEntry:
        """This entry bound to one level's column: its reference and the column of its id."""
        return self.model_copy(
            update={
                "entry_id": f"{self.entry_id.rpartition('/')[0]}/{name}",
                "reference": self.reference.bound(name),
            }
        )


class Key(FrozenModel):
    """One access key of a set: the name callers ask by, standing for a kind and the qualifier
    values it fixes; a qualifier it does not fix stays open."""

    key: str
    kind: str
    fixed: dict[str, str] = Field(default_factory=dict)
    psi_ms: tuple[str, ...] = ()

    def accepted(self) -> dict[str, tuple[str, ...]]:
        """The qualifier values a request for this key accepts, besides its kind."""
        return {name: (value,) for name, value in self.fixed.items()}

    def describes(self, kind: str, qualifiers: Mapping[str, str], /) -> bool:
        """Whether an entry of this kind with these qualifiers has this key."""
        return kind == self.kind and all(
            qualifiers.get(name) == value for name, value in self.fixed.items()
        )


class RuleVariant(FrozenModel):
    """One packaged rule level: a level APB2 converts for one software version pattern."""

    level: str
    software_version_pattern: str


class SourceCatalogue(FrozenModel):
    """Every reviewed rule variant of one vendor and the entries one consumer needs from it."""

    software_name: str
    variants: tuple[RuleVariant, ...]
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> SourceCatalogue:
        if _ids_repeat(self.entries):
            raise ValueError(f"{self.software_name}: duplicate entry ids")
        declared = {(variant.software_version_pattern, variant.level) for variant in self.variants}
        if len(declared) != len(self.variants):
            raise ValueError(f"{self.software_name}: duplicate rule variants")
        for entry in self.entries:
            if not entry.software_version_pattern:
                raise ValueError(f"{self.software_name}: {entry.reference} lists no version")
            if entry.reference.name is None:
                raise ValueError(f"{self.software_name}: a vendor entry names its column")
            if entry.reference.level == ANY:
                raise ValueError(f"{self.software_name}: a vendor entry names its level")
            undeclared = {
                (pattern, entry.reference.level) for pattern in entry.software_version_pattern
            } - declared
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
            if variant.software_version_pattern in entry.software_version_pattern
            and entry.reference.level == variant.level
        )


class ProducerCatalogue(FrozenModel):
    """Fields an app such as apb-fasta writes after conversion, on every software's level.

    ``requires`` is the metadata path that records the app's run. Until a required run is
    recorded, its entries are pending and ``instruction`` says what to run.
    """

    producer: str
    requires: tuple[str, ...] = ()
    instruction: str | None = None
    entries: tuple[SourceEntry, ...]

    @model_validator(mode="after")
    def _consistent(self) -> ProducerCatalogue:
        if _ids_repeat(self.entries):
            raise ValueError(f"{self.label}: duplicate entry ids")
        if any(entry.software_version_pattern for entry in self.entries):
            raise ValueError(f"{self.label}: app entries apply to every software version")
        if any(entry.reference.prefix is not None for entry in self.entries):
            raise ValueError(f"{self.label}: prefixes belong to annotation catalogues")
        if bool(self.requires) != (self.instruction is not None):
            raise ValueError(f"{self.label}: an instruction comes with a required run")
        return self

    @property
    def label(self) -> str:
        """Who the entries come from: the app."""
        return self.producer

    def entries_on(self, level: str) -> tuple[SourceEntry, ...]:
        """Return the entries this producer supplies on one level, those of every level included."""
        return tuple(found for entry in self.entries if (found := entry.on(level)) is not None)

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
        if _ids_repeat(self.entries):
            raise ValueError(f"{self.label}: duplicate entry ids")
        if any(entry.software_version_pattern for entry in self.entries):
            raise ValueError(f"{self.label}: annotation entries apply to every software version")
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
        """Return the entries this convention supplies on one level, those of every level
        included."""
        return tuple(found for entry in self.entries if (found := entry.on(level)) is not None)


class RequirementRow(FrozenModel):
    """How strongly a consumer needs one meaning on one level: a field location and a key."""

    level: str
    location: Location
    key: str
    requirement: Requirement

    def describes(self, entry: SourceEntry, /) -> bool:
        """Whether an entry on this row's level answers the row."""
        return (
            entry.reference.level in (self.level, ANY)
            and entry.reference.location in READS[self.location]
            and entry.key == self.key
        )

    def asked(self, level: str, location: Location, key: str | None) -> bool:
        """Whether a request on one level and location asks for this row's key."""
        return level == self.level and location == self.location and key == self.key


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

    ``producers`` hold the fields apps write after conversion and ``annotations`` the
    sample-annotation fields; both apply to every software version. A set made only of them has no vendor catalogue and needs
    no review. ``requirements`` are the consumer's requirement rows; a set without them is
    checked for coverage only. ``keys`` are the set's access keys; each entry has exactly one.
    """

    __slots__ = (
        "_by_key",
        "_by_version",
        "annotations",
        "catalogues",
        "description",
        "keys",
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
        keys: tuple[Key, ...] = (),
    ) -> None:
        self.vocabulary = vocabulary
        self.vocabulary_version = vocabulary_version
        self.description = description
        self.catalogues = catalogues
        self.producers = producers
        self.annotations = annotations
        self.requirements = requirements
        self.keys = keys
        self._by_key = {found.key: found for found in keys}
        if len(self._by_key) != len(keys):
            raise ValueError("a key repeats in the set")
        self._by_version: dict[tuple[str, str, str], ReviewedRule] = {}
        entries = [entry for source in self.sources() for entry in source.entries]
        if _ids_repeat(entries):
            raise ValueError("an entry id repeats across the set's catalogues")
        _check_keys(vocabulary, keys, entries)
        for row in requirements:
            if row.key not in self._by_key:
                raise ValueError(f"requirement on {row.level}: unknown key {row.key!r}")
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

    def key(self, name: str, /) -> Key:
        """Return one of the set's access keys.

        Raises:
            ValueError: The set has no such key.
        """
        if name not in self._by_key:
            raise ValueError(f"unknown key {name!r}; keys: {sorted(self._by_key)}")
        return self._by_key[name]

    def has_key(self, name: str, /) -> bool:
        """Whether the set has this key."""
        return name in self._by_key

    def requirement_for(
        self, level: str, location: Location, key: str | None
    ) -> RequirementRow | None:
        """Return the requirement row a request asks for, if any."""
        return next((row for row in self.requirements if row.asked(level, location, key)), None)


def _ids_repeat(entries: Sequence[SourceEntry], /) -> bool:
    """Whether two entries share an id and a key; one id may carry two kinds."""
    ids = [(entry.entry_id, entry.key) for entry in entries]
    return len(ids) != len(set(ids))


def _check_keys(
    vocabulary: SetVocabulary, keys: Sequence[Key], entries: Sequence[SourceEntry]
) -> None:
    """Require every key to name admitted values and every entry to carry admitted qualifiers
    and the kind and fixed values of the key it records; another key may describe it too."""
    by_key = {found.key: found for found in keys}
    for found in keys:
        try:
            vocabulary.check_predicate(found.kind, found.accepted())
        except ValueError as error:
            raise ValueError(f"key {found.key!r}: {error}") from error
    for entry in entries:
        try:
            vocabulary.check_description(entry.kind, entry.qualifiers)
        except ValueError as error:
            raise ValueError(f"{entry.entry_id}: {error}") from error
        key = by_key.get(entry.key)
        if key is None or not key.describes(entry.kind, entry.qualifiers):
            raise ValueError(f"{entry.entry_id}: its key {entry.key!r} does not describe it")


class CatalogueDescription(FrozenModel):
    """What one catalogue set holds and who uses it."""

    purpose: str
    used_by: tuple[str, ...]


TABLES = (
    "sets",
    "terms",
    "kinds",
    "qualifiers",
    "qualifier_values",
    "catalog",
    "producers",
)
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
        ValueError: A table has rows of a set that ``sets.csv`` does not describe.
    """
    names = [row["set"] for row in _table(folder, "sets")]
    for table in TABLES:
        stray = sorted({row["set"] for row in _table(folder, table)} - set(names))
        if stray:
            raise ValueError(f"{table}.csv has rows of undescribed sets {stray}")
    return names


def _load(folder: Traversable, name: str, /) -> SourceCatalogues:
    """Load one set's rows from a folder of catalogue tables and check them.

    An entry id names the entry's source and version: vendor entries their conversion software and
    a label of ``versions.csv``, or ``*`` for every version; such a set reviews every level the
    packaged entries name for each version. A source ``producers.csv`` names is an app; its entries
    and ``annotation:<convention>`` entries apply to every software version.
    """

    def rows(table: str) -> list[Row]:
        return [row for row in _table(folder, table) if row["set"] == name]

    description, vocabulary = _vocabulary(
        name, rows("sets"), rows("kinds"), rows("qualifiers"), rows("qualifier_values")
    )
    keys, requirements = _terms(name, vocabulary, rows("terms"))
    by_key = {found.key: found for found in keys}
    _check_mapped(name, rows("catalog"), rows("terms"), by_key)
    fields: dict[tuple[str, str], list[Row]] = {}
    for row in rows("catalog"):
        fields.setdefault((_entry_id(row), row["key"]), []).append(row)
    by_source: dict[str, list[SourceEntry]] = {}
    for (found, key), field in fields.items():
        named = entry_id(found)
        entry = _entry(name, field, named, by_key[key])
        by_source.setdefault(named.source, []).append(entry)
    runs = {row["producer"]: row for row in rows("producers")}
    vendors: dict[str, tuple[SourceEntry, ...]] = {}
    producers: list[ProducerCatalogue] = []
    annotations: list[AnnotationCatalogue] = []
    for source, entries in by_source.items():
        prefix, _, named = source.partition(":")
        if prefix == "annotation":
            annotations.append(
                AnnotationCatalogue.model_validate({"convention": named, "entries": entries})
            )
        elif source in runs:
            run = runs.pop(source)
            producers.append(
                ProducerCatalogue(
                    producer=source,
                    requires=tuple(run["requires"].split(".")) if run["requires"] else (),
                    instruction=run["instruction"] or None,
                    entries=tuple(entries),
                )
            )
        else:
            vendors[source] = tuple(entries)
    if runs:
        raise ValueError(f"{name}: producers.csv names apps without entries {sorted(runs)}")
    return SourceCatalogues(
        vocabulary,
        catalog_version(),
        _vendors(name, vendors),
        description,
        tuple(producers),
        tuple(annotations),
        requirements,
        keys,
    )


def _vocabulary(
    name: str,
    sets: Sequence[Row],
    kinds: Sequence[Row],
    qualifiers: Sequence[Row],
    values: Sequence[Row],
) -> tuple[CatalogueDescription, SetVocabulary]:
    """A set's description and vocabulary from its row of ``sets.csv``, its kinds, its qualifiers
    and their values.

    Raises:
        ValueError: ``sets.csv`` describes the set other than once, ``qualifiers.csv`` declares
            ``kind``, or ``qualifier_values.csv`` defines a value of no qualifier.
    """
    if len(sets) != 1:
        raise ValueError(f"sets.csv has {len(sets)} rows describing the set {name!r}")
    head = sets[0]
    definitions = {row["qualifier"]: row["definition"] for row in qualifiers}
    if "kind" in definitions:
        raise ValueError(f"{name}: qualifiers.csv declares 'kind'; kinds.csv holds the kinds")
    defined: dict[str, dict[str, str]] = {qualifier: {} for qualifier in definitions}
    for row in values:
        if row["qualifier"] not in defined:
            raise ValueError(
                f"{name}: qualifier_values.csv defines {row['value']!r} of no qualifier"
            )
        defined[row["qualifier"]][row["value"]] = row["definition"]
    description = _description(head)
    vocabulary = SetVocabulary(
        prefix=head["prefix"],
        definition=head["definition"],
        kind_definition=head["kind_definition"],
        kinds={row["kind"]: row["definition"] for row in kinds},
        qualifiers={
            qualifier: Qualifier(definition=definition, values=defined[qualifier])
            for qualifier, definition in definitions.items()
        },
    )
    return description, vocabulary


def _description(head: Row) -> CatalogueDescription:
    """What a set holds and who uses it, from its ``sets.csv`` row."""
    return CatalogueDescription(purpose=head["purpose"], used_by=tuple(head["used_by"].split(";")))


def _check_mapped(
    name: str, rows: Sequence[Row], terms: Sequence[Row], keys: Mapping[str, Key], /
) -> None:
    """Require every ``catalog.csv`` row to map a term ``terms.csv`` defines at its location and
    to agree with the term's key: its kind and PSI-MS terms, and ``fixed`` true exactly on the
    qualifiers the key fixes, with the value it fixes. Log a warning for each term no row maps
    yet; a row of every level (``*``) maps the term on each level.

    Raises:
        ValueError: A row maps no term, is no valid qualifier pair, or disagrees with its key.
    """
    places = {(row["key"], row["location"]) for row in terms}
    stray = sorted({(row["key"], row["location"]) for row in rows} - places)
    if stray:
        raise ValueError(f"{name}: catalog.csv maps terms terms.csv does not define: {stray}")
    for row in rows:
        _check_row(f"{name}: {_entry_id(row)}", row, keys[row["key"]])
    mapped = {(row["key"], row["location"]) for row in rows}
    everywhere = {
        (key, location.partition("/")[2]) for key, location in mapped if location.startswith("*/")
    }
    unmapped = [
        term
        for term in dict.fromkeys((row["key"], row["location"]) for row in terms)
        if term not in mapped and (term[0], term[1].partition("/")[2]) not in everywhere
    ]
    if unmapped:
        logger.warning("%s: no catalog.csv row maps the terms %s yet", name, unmapped)


def _check_row(label: str, row: Row, key: Key, /) -> None:
    """Require one ``catalog.csv`` row to agree with its key.

    Raises:
        ValueError: The row is no valid qualifier pair, or its kind, PSI-MS terms or ``fixed``
            differ from what its key states.
    """
    pair = _pair(label, row)
    psi_ms = ";".join(key.psi_ms)
    if (row["kind"], row["psi_ms"]) != (key.kind, psi_ms):
        raise ValueError(
            f"catalog.csv: {label} has the kind {row['kind']!r} and the PSI-MS terms "
            f"{row['psi_ms']!r}; its key {key.key!r} has {key.kind!r} and {psi_ms!r}"
        )
    fixes = row["fixed"] == "true"
    if fixes != (row["qualifier"] in key.fixed) or (
        fixes and not pair.items() <= key.fixed.items()
    ):
        raise ValueError(
            f"catalog.csv: {label} has fixed {row['fixed']!r} for {pair}; its key {key.key!r} "
            f"fixes {key.fixed}"
        )


def _entry_id(row: Row, /) -> str:
    """A ``catalog.csv`` row's entry id, its software, location and name joined by ``/``."""
    return f"{row['software']}/{row['location']}/{row['name']}"


def _pair(label: str, row: Row, /) -> dict[str, str]:
    """A row's qualifier and value as one mapping, empty when the row has neither.

    Raises:
        ValueError: The row has a qualifier without a value or a value without a qualifier, its
            qualifier is ``kind``, or its ``fixed`` is neither ``true`` nor ``false``, or
            ``true`` without a qualifier.
    """
    qualifier, value, fixed = row["qualifier"], row["value"], row["fixed"]
    if bool(qualifier) != bool(value):
        raise ValueError(f"catalog.csv: {label} has a qualifier and a value only together")
    if qualifier == "kind":
        raise ValueError(f"catalog.csv: {label} qualifies the kind, which its kind column holds")
    if fixed not in ("true", "false") or (fixed == "true" and not qualifier):
        raise ValueError(
            f"catalog.csv: {label} has fixed {fixed!r}; true on a row with a qualifier, else false"
        )
    return {qualifier: value} if qualifier else {}


def _terms(
    name: str, vocabulary: SetVocabulary, rows: Sequence[Row]
) -> tuple[tuple[Key, ...], Requirements]:
    """A set's keys and requirements from its ``terms.csv`` rows. A term is one key at one
    location, with one row per qualifier value its key fixes, or one row with neither; its
    requirement, if any, is the same on all its rows.

    Raises:
        ValueError: A key is inconsistent (see :func:`_key`) or names a kind or value the
            vocabulary does not admit, or a term has two requirements or one not admitted.
    """
    by_key: dict[str, list[Row]] = {}
    by_term: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        by_key.setdefault(row["key"], []).append(row)
        by_term.setdefault((row["key"], row["location"]), []).append(row)
    keys = tuple(_key(name, key, found) for key, found in by_key.items())
    for found in keys:
        try:
            vocabulary.check_predicate(found.kind, found.accepted())
        except ValueError as error:
            raise ValueError(f"{name}: key {found.key!r}: {error}") from error
    requirements: list[RequirementRow] = []
    for (key, location), found in by_term.items():
        needs = sorted({row["requirement"] for row in found})
        if len(needs) != 1:
            raise ValueError(f"{name}: term {key!r} at {location} has the requirements {needs}")
        if needs[0]:
            level, _, attribute = location.partition("/")
            requirements.append(
                RequirementRow.model_validate(
                    {"level": level, "location": attribute, "key": key, "requirement": needs[0]}
                )
            )
    return keys, tuple(requirements)


def _key(name: str, key: str, rows: Sequence[Row], /) -> Key:
    """One key from its ``terms.csv`` rows: one kind and one PSI-MS term list on every row, and
    the same qualifier values fixed at every location.

    Raises:
        ValueError: The key has two kinds or PSI-MS term lists, a row has half a qualifier pair
            or qualifies the kind, a term mixes a row without a pair with pair rows, or two
            locations fix different values.
    """
    kinds = sorted({row["kind"] for row in rows})
    terms = sorted({row["psi_ms"] for row in rows})
    if len(kinds) != 1 or len(terms) != 1:
        raise ValueError(
            f"{name}: key {key!r} has the kinds {kinds} and the PSI-MS terms {terms}; every row "
            "of a key has one of each"
        )
    by_location: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        qualifier, value = row["qualifier"], row["value"]
        if bool(qualifier) != bool(value) or qualifier == "kind":
            raise ValueError(
                f"terms.csv: {name}: {key!r} at {row['location']} has the qualifier "
                f"{qualifier!r} and the value {value!r}; a pair names a qualifier other than kind"
            )
        by_location.setdefault(row["location"], []).append((qualifier, value))
    fixes: set[tuple[tuple[str, str], ...]] = set()
    for location, pairs in by_location.items():
        if ("", "") in pairs and len(pairs) > 1:
            raise ValueError(f"terms.csv: {name}: {key!r} at {location} has a row without a pair")
        fixes.add(tuple(sorted(pair for pair in pairs if pair != ("", ""))))
    if len(fixes) != 1:
        raise ValueError(
            f"{name}: key {key!r} fixes {sorted(fixes)} at different locations; a key fixes the "
            "same values everywhere"
        )
    return Key(
        key=key,
        kind=kinds[0],
        fixed=dict(fixes.pop()),
        psi_ms=tuple(terms[0].split(";")) if terms[0] else (),
    )


def _entry(name: str, rows: Sequence[Row], named: EntryId, key: Key) -> SourceEntry:
    """One entry from its ``catalog.csv`` rows, one per qualifier, its parsed id and its key;
    the table's primary key keeps a qualifier to one row.

    Raises:
        ValueError: The rows differ in basis or evidence.
    """
    label = f"{name}: {_entry_id(rows[0])}"
    qualifiers = {
        qualifier: value for row in rows for qualifier, value in _pair(label, row).items()
    }
    evidence = {(row["basis"], row["evidence_url"]) for row in rows}
    if len(evidence) != 1:
        raise ValueError(f"catalog.csv: {label} has two bases or evidence URLs; one per field")
    basis, url = evidence.pop()
    prefix = named.name.removesuffix("*") if named.name.endswith("*") else None
    reference = Reference(
        level=named.level,
        location=named.attribute,
        table=named.table,
        name=None if prefix is not None else named.name,
        prefix=prefix,
    )
    return SourceEntry(
        entry_id=_entry_id(rows[0]),
        software_version_pattern=version_patterns(named.source, named.version),
        reference=reference,
        key=key.key,
        kind=key.kind,
        qualifiers=qualifiers,
        evidence=Evidence(basis=basis, source=url or None),
    )


def _vendors(
    name: str, entries: Mapping[str, tuple[SourceEntry, ...]]
) -> tuple[SourceCatalogue, ...]:
    """One catalogue per software of ``versions.csv``, each reviewing every level the packaged
    entries name for its versions, when the set has vendor entries; none otherwise."""
    if not entries:
        return ()
    variants: dict[str, list[RuleVariant]] = {}
    for found in rule_levels():
        variants.setdefault(found.software_name, []).append(
            RuleVariant(level=found.level, software_version_pattern=found.software_version_pattern)
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
    heads = {row["set"]: row for row in _table(_data(), "sets")}
    return {name: _description(heads[name]) for name in _set_names(_data())}


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
        ValueError: A plugin set has a packaged set's name, or two sets share a prefix.
    """
    packaged = packaged_descriptions()
    plugins = _plugin_folders()
    clashing = sorted(set(packaged) & set(plugins))
    if clashing:
        raise ValueError(f"plugin catalogue sets {clashing} have the names of packaged sets")
    prefixes = {
        **_packaged_prefixes(),
        **{name: _plugin_set(name).vocabulary.prefix for name in plugins},
    }
    shared = sorted(prefix for prefix, count in Counter(prefixes.values()).items() if count > 1)
    if shared:
        raise ValueError(f"catalogue sets share the prefixes {shared}: {prefixes}")
    return {**packaged, **{name: _plugin_set(name).description for name in plugins}}


@cache
def _packaged_prefixes() -> dict[str, str]:
    """Every packaged set's prefix, by set name, from ``sets.csv``."""
    return {row["set"]: row["prefix"] for row in _table(_data(), "sets")}


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
