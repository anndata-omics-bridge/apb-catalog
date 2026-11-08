"""Look up APB fields by meaning, so callers never name vendor columns.

:class:`Catalog` answers column names from a software and version, without data;
:class:`DataCatalog` answers a result's data.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Literal, cast

import polars as pl
from apb2.api import JsonValue, ParsedLevel, ParsedLevels

from apb_catalog import rules
from apb_catalog.levels import Level, LevelNames, Lookup
from apb_catalog.resolver import (
    AbsentLevel,
    FieldRequest,
    LevelView,
    PendingEntry,
    ProducedLevel,
    Resolution,
    ReviewedLevel,
    UnresolvedField,
    UnreviewedLevel,
)
from apb_catalog.rules import ANY, Address, Location
from apb_catalog.snapshot import ResolutionSnapshot, this_producer
from apb_catalog.source import (
    AnnotationCatalogue,
    CatalogueDescription,
    ProducerCatalogue,
    RequirementRow,
    SourceCatalogues,
    SourceEntry,
    catalogue_set,
)
from apb_catalog.source import Reference as SourceReference
from apb_catalog.table import entry_row

METADATA_KEY = "catalog"
_LOG = logging.getLogger("apb_catalog")

type Enforce = Literal["required", "recommended"] | None


class MissingRequiredField(LookupError):
    """Fields the named sets require are absent from the rule or the result, under ``enforce``."""

    def __init__(self, missing: tuple[tuple[Resolution, RequirementRow], ...]) -> None:
        super().__init__("\n".join(_missing_line(resolution, row) for resolution, row in missing))
        self.missing = missing


def _missing_line(resolution: Resolution, row: RequirementRow) -> str:
    """One missing field: its requirement, what was asked, on which level, and why it is absent."""
    return (
        f"{row.requirement} field {resolution.request.wanted()} on {row.level} is missing: "
        f"{'; '.join(resolution.reasons)}"
    )


def _bind(entry: SourceEntry, obs_columns: tuple[str, ...]) -> tuple[SourceEntry, ...]:
    """The entry bound to the level's column: by name or by prefix.

    A prefix matching several columns binds to each, so the lookup reports them as ambiguous.
    """
    reference = entry.reference
    if reference.prefix is not None:
        prefix = reference.prefix.lower()
        return tuple(
            entry.bound(column) for column in obs_columns if column.lower().startswith(prefix)
        )
    return (entry,)


def level_view(
    name: str,
    software: str | None,
    pattern: str | None,
    rule_level: str | None,
    catalogues: SourceCatalogues,
    *,
    retained: frozenset[Address] | set[Address],
    obs_columns: tuple[str, ...] = (),
    ran: Callable[[ProducerCatalogue], bool],
    annotations: tuple[AnnotationCatalogue, ...] = (),
) -> LevelView:
    """Bind one level to its set: the reviewed vendor entries, then the apps' and annotations'.

    Only entries whose field the level holds answer; an app that has not run leaves its entries
    pending. A set with vendor catalogues answers only for a reviewed software version.
    """
    if software is None or pattern is None or rule_level is None:
        return UnreviewedLevel(name, None, None, "the level records no rule_json software version")
    entries: list[SourceEntry] = []
    pending: list[PendingEntry] = []
    reviewed = catalogues.reviewed(software, pattern, rule_level)
    if catalogues.needs_review:
        if reviewed is None:
            return UnreviewedLevel(
                name,
                software,
                pattern,
                f"no source catalogue reviewed {software} {pattern} {rule_level}",
            )
        entries += [entry for entry in reviewed.entries() if entry.reference.address() in retained]
    for producer in catalogues.producers:
        offered = [
            bound
            for entry in producer.entries_on(rule_level)
            for bound in _bind(entry, obs_columns)
        ]
        if ran(producer):
            entries += [entry for entry in offered if entry.reference.address() in retained]
        else:
            pending += [PendingEntry(entry, producer.pending_reason()) for entry in offered]
    for annotation in annotations:
        entries += [
            bound
            for entry in annotation.entries_on(rule_level)
            for bound in _bind(entry, obs_columns)
        ]
    if reviewed is not None:
        return ReviewedLevel(name, reviewed, tuple(entries), tuple(pending))
    return ProducedLevel(name, software, pattern, tuple(entries), tuple(pending))


class _Lookups:
    """The requests, answers and snapshot both catalogues share for one set."""

    __slots__ = ("catalogues", "name", "resolutions", "views")

    def __init__(
        self, name: str, catalogues: SourceCatalogues, views: dict[str, LevelView]
    ) -> None:
        self.name = name
        self.catalogues = catalogues
        self.views = views
        self.resolutions: list[Resolution] = []

    def request(
        self, level: str, location: Location, key: str | None, qualifiers: Mapping[str, str]
    ) -> FieldRequest:
        """The request for a key, or for every key when ``key`` is ``None``, narrowed by further
        qualifiers.

        Raises:
            ValueError: The set has no such key, or a qualifier names the kind or a value the key
                already fixes.
        """
        found = None if key is None else self.catalogues.key(key)
        fixed = {} if found is None else found.accepted()
        clashing = sorted(({"kind"} | set(fixed)) & set(qualifiers))
        if clashing:
            raise ValueError(f"ask by key; {key or 'the lookup'} fixes {', '.join(clashing)}")
        return FieldRequest(
            level=level,
            location=location,
            key=key,
            kind=None if found is None else found.kind,
            qualifiers=fixed | {name: (value,) for name, value in qualifiers.items()},
        )

    def answer(self, request: FieldRequest) -> Resolution:
        self.catalogues.vocabulary.check_predicate(request.kind, request.qualifiers)
        return self.views.get(request.level, AbsentLevel(request.level)).resolve(request)

    def resolve(self, request: FieldRequest) -> Resolution:
        resolution = self.answer(request)
        self.record(resolution)
        return resolution

    def record(self, resolution: Resolution) -> None:
        """Keep an answer for the snapshot, once however often it is asked."""
        if resolution not in self.resolutions:
            self.resolutions.append(resolution)

    def lookup(
        self, level: str, location: Location, key: str, qualifiers: Mapping[str, str]
    ) -> Resolution:
        """The recorded answer to one key; requirements were checked when the catalog opened."""
        return self.resolve(self.request(level, location, key, qualifiers))

    def missing(self) -> list[tuple[Resolution, RequirementRow]]:
        """Every required or recommended field a bound level lacks, recorded with its
        requirement; a field the catalogue cannot decide is not missing."""
        found: list[tuple[Resolution, RequirementRow]] = []
        for row in self.catalogues.requirements:
            if row.requirement == "optional" or row.level not in self.views:
                continue
            resolution = self.answer(self.request(row.level, row.location, row.key, {}))
            if resolution.status != "missing":
                continue
            resolution = resolution.model_copy(update={"requirement": row.requirement})
            self.record(resolution)
            found.append((resolution, row))
        return found

    def find(
        self, level: str, location: Location, key: str, qualifiers: Mapping[str, str]
    ) -> SourceReference | None:
        """The one field asked for, ``None`` when the level has none."""
        return self.lookup(level, location, key, qualifiers).found()

    def find_all(self, level: str, location: Location, key: str) -> tuple[SourceReference, ...]:
        """Every field one key names on a level: each match of an ambiguous answer.

        Raises:
            UnresolvedField: A field the key may name is undecided, or its producer has not run.
        """
        resolution = self.lookup(level, location, key, {})
        if resolution.status != "ambiguous":
            found = resolution.found()
            return () if found is None else (found,)
        answering = {entry.reference.address() for entry in self.views[level].entries}
        if any(
            candidate.undecided or candidate.reference.address() not in answering
            for candidate in resolution.candidates
        ):
            raise UnresolvedField(resolution)
        return tuple(candidate.reference for candidate in resolution.candidates)

    def alone(self) -> Lookup:
        """How this set alone answers keys, as a name with its prefix asks it."""
        return Lookup(
            field=self.find,
            fields=self.find_all,
            offered=lambda level, location: self.keys(level, location, {}),
            known=frozenset(found.key for found in self.catalogues.keys),
            sets={},
        )

    def keys(
        self, level: str, location: Location, qualifiers: Mapping[str, str]
    ) -> tuple[str, ...]:
        """The keys a field the level holds answers; a later producer's keys wait until it runs,
        so every key listed reads."""
        resolution = self.answer(self.request(level, location, None, qualifiers))
        view = self.views.get(level)
        held: set[Address] = (
            set() if view is None else {entry.reference.address() for entry in view.entries}
        )
        answering = {
            candidate.key
            for candidate in resolution.candidates
            if candidate.reference.address() in held
        }
        return tuple(key for key in resolution.offered() if key in answering)

    def entries(self) -> tuple[SourceEntry, ...]:
        return tuple(entry for view in self.views.values() for entry in view.entries)

    def snapshot(self) -> ResolutionSnapshot:
        return ResolutionSnapshot(
            producer=this_producer(),
            catalogue=self.name,
            description=self.catalogues.description,
            vocabulary_version=self.catalogues.vocabulary_version,
            vocabulary=self.catalogues.vocabulary,
            levels=tuple(view.binding() for view in self.views.values()),
            entries=self.entries(),
            resolutions=tuple(self.resolutions),
        )

    def rows(self, view: LevelView, entries: tuple[SourceEntry, ...]) -> list[dict[str, object]]:
        binding = view.binding()
        return [
            entry_row(
                self.name, self.catalogues, entry.source, binding.software_version_pattern, entry
            )
            for entry in entries
        ]


def _catalogued(catalogues: SourceCatalogues, level: str) -> set[Address]:
    """Every field the set's entries name on one level: without data, the catalogue says what a
    level holds."""
    return {
        entry.reference.address()
        for source in catalogues.sources()
        for entry in source.entries
        if entry.reference.level in (level, ANY) and entry.reference.name is not None
    }


class Catalog:
    """Which column one software version reports for each meaning, without any data.

    ``Catalog("DIA-NN", "2.6.0", "abundance_alpha").levels["peptidoform_ion"].layers["intensity"]`` is
    ``'Precursor_Quantity'``: the slots of :class:`DataCatalog`'s levels, holding names. The
    packaged rule levels whose version pattern admits ``version`` give the levels; the set's
    entries for that pattern give each level's fields. A slot's ``get`` returns the name or
    ``None`` and takes further qualifiers, such as ``unit="minute"``. ``enforce`` checks the
    set's requirements against the rule's levels once, here.

    Raises:
        ValueError: No packaged rule of the software admits the version, or ``enforce`` is set
            and the set has no requirements.
        MissingRequiredField: Under ``enforce``, the rule lacks fields the set requires.
    """

    __slots__ = ("_lookups", "levels")

    def __init__(self, software: str, version: str, catalog: str, enforce: Enforce = None) -> None:
        catalogues = catalogue_set(catalog)
        matched = rules.matching(software, version)
        if not matched:
            known = sorted(
                {
                    found.software_version_pattern
                    for found in rules.rule_levels()
                    if found.software_name.lower() == software.lower()
                }
            )
            raise ValueError(
                f"no packaged {software} rule admits version {version!r}; patterns: {known}"
            )
        views: dict[str, LevelView] = {}
        for found in matched:
            views[found.level] = level_view(
                found.level,
                found.software_name,
                found.software_version_pattern,
                found.level,
                catalogues,
                retained=_catalogued(catalogues, found.level),
                ran=lambda producer: not producer.requires,
            )
        self._lookups = _Lookups(catalog, catalogues, views)
        _enforce((self._lookups,), enforce)
        lookup = Lookup(
            field=self._key_field,
            fields=self._lookups.find_all,
            offered=self._offered,
            known=frozenset(found.key for found in catalogues.keys),
            sets={catalogues.vocabulary.prefix: self._lookups.alone()},
        )
        self.levels = {name: LevelNames(name, lookup) for name in views}

    @property
    def description(self) -> CatalogueDescription:
        """What this catalogue set holds and who uses it."""
        return self._lookups.catalogues.description

    def fields(self) -> pl.DataFrame:
        """Every catalogued field the rule declares, one row per field, as ``apb-catalog table``
        shows them, with ``present`` true for each."""
        rows = [
            {**row, "present": True, "constant": None}
            for view in self._lookups.views.values()
            for row in self._lookups.rows(view, view.entries)
        ]
        return _fields_frame(rows)

    def _key_field(
        self, level: str, location: Location, key: str, qualifiers: Mapping[str, str]
    ) -> SourceReference | None:
        return self._lookups.find(level, location, key, qualifiers)

    def _offered(self, level: str, location: Location) -> tuple[str, ...]:
        return self._lookups.keys(level, location, {})


@dataclass(frozen=True, slots=True)
class LevelFields:
    """What a catalog binds one level of a result by: its rule's software version and the
    fields it holds."""

    rule: tuple[str, str, str] | None
    """Software name, version pattern and level of the rule the level records, if any."""
    retained: frozenset[Address]
    """Every field the level holds."""
    obs_columns: tuple[str, ...]
    """The level's obs columns, which prefix entries bind to."""

    @classmethod
    def of(cls, level: ParsedLevel) -> LevelFields:
        return cls(rule_version(level), frozenset(_retained(level)), tuple(level.obs.frame.columns))


class ComposedSets:
    """The sets one result's levels are bound to, the named ones alone: a key routes to the sets
    that define it, and two sets naming different fields for one key on one level is an error.

    Raises:
        ValueError: A named set can answer nothing on the result, two sets name different fields
            for one key, or ``enforce`` is set and no named set has requirements.
        MissingRequiredField: Under ``enforce``, a field the named sets require is missing.
    """

    __slots__ = ("known", "sets")

    def __init__(
        self,
        levels: Mapping[str, LevelFields],
        metadata: Mapping[str, object],
        catalogs: tuple[str, ...],
        enforce: Enforce,
    ) -> None:
        self.sets = {
            name: _data_lookups(levels, metadata, name) for name in dict.fromkeys(catalogs)
        }
        _check_shared_keys(self.sets)
        self.known = frozenset(
            found.key for lookups in self.sets.values() for found in lookups.catalogues.keys
        )
        _enforce(tuple(self.sets.values()), enforce)

    def lookup(self) -> Lookup:
        """How the levels answer keys."""
        return Lookup(
            field=self.find,
            fields=self.find_all,
            offered=self.offered,
            known=self.known,
            sets={
                lookups.catalogues.vocabulary.prefix: lookups.alone()
                for lookups in self.sets.values()
            },
        )

    def first(self) -> _Lookups:
        """The first set named.

        Raises:
            ValueError: No set was named.
        """
        if not self.sets:
            raise ValueError("no catalogue set named")
        return next(iter(self.sets.values()))

    def defining(self, key: str, qualifiers: Mapping[str, str] | None = None) -> list[_Lookups]:
        """The sets that define a key and declare every further qualifier asked; the first set
        that defines it when none declares them, so its lookup names what it lacks."""
        found = [lookups for lookups in self.sets.values() if lookups.catalogues.has_key(key)]
        if not found:
            raise ValueError(f"unknown key {key!r}; keys: {sorted(self.known)}")
        declaring = [
            lookups
            for lookups in found
            if set(qualifiers or {}) <= set(lookups.catalogues.vocabulary.qualifiers)
        ]
        return declaring or found[:1]

    def find(
        self, level: str, location: Location, key: str, qualifiers: Mapping[str, str]
    ) -> SourceReference | None:
        """The field one key names, asked of every set that defines the key; the first found."""
        found: SourceReference | None = None
        for lookups in self.defining(key, qualifiers):
            reference = lookups.find(level, location, key, qualifiers)
            found = found or reference
        return found

    def find_all(self, level: str, location: Location, key: str) -> tuple[SourceReference, ...]:
        """Every field one key names, from every set that defines the key."""
        found: dict[Address, SourceReference] = {}
        for lookups in self.defining(key):
            for reference in lookups.find_all(level, location, key):
                found.setdefault(reference.address(), reference)
        return tuple(found.values())

    def offered(self, level: str, location: Location) -> tuple[str, ...]:
        """The keys the level offers at one location, from every set."""
        return tuple(
            sorted(
                {key for lookups in self.sets.values() for key in lookups.keys(level, location, {})}
            )
        )


class DataCatalog:
    """What one APB result's fields mean to its consumers, with the data handed back directly.

    ``DataCatalog(result, "abundance_alpha", "confidence_alpha")`` composes those sets alone;
    ``apb_alpha``, the fields apb2 convert writes, answers only when named. A key routes to the
    sets that define it; two sets naming different fields for one key on one level is an error.
    With no set named, every name is the level's own. The first set named supplies
    :attr:`description` and the default :meth:`snapshot`. Requirements are checked once, here:
    ``enforce`` raises :class:`MissingRequiredField` listing every missing field.

    ``levels["peptidoform_ion"].layers["pep"]`` is MaxQuant's ``PEP`` or Spectronaut's
    ``EG_PEP`` matrix, as AnnData returns it; a name that is no key reads the level's own field
    of that name, as cf_xarray does. ``layers.get("pep")`` is ``None`` when the vendor reports no
    PEP or APB2 left it out because it held one value or none, ``layers.name("pep")`` the
    layer's name; both take further qualifiers. Ambiguous or unreviewed answers raise
    :class:`~apb_catalog.resolver.UnresolvedField`.
    """

    __slots__ = ("_parsed", "_sets", "levels")

    def __init__(self, result: ParsedLevels, *catalogs: str, enforce: Enforce = None) -> None:
        self._parsed = result
        self._sets = ComposedSets(
            {name: LevelFields.of(level) for name, level in result.levels.items()},
            result.metadata,
            catalogs,
            enforce,
        )
        lookup = self._sets.lookup()
        self.levels = {name: Level(name, level, lookup) for name, level in result.levels.items()}

    @property
    def description(self) -> CatalogueDescription:
        """What the first catalogue set named holds and who uses it."""
        return self._sets.first().catalogues.description

    def fields(self) -> pl.DataFrame:
        """Every catalogued field of the result in every composed set, one row per field, as
        ``apb-catalog table`` shows them, with ``present`` and, for a field APB2 left out
        because it held one value, that ``constant``."""
        rows: list[dict[str, object]] = []
        for lookups in self._sets.sets.values():
            for name, view in lookups.views.items():
                rows += [
                    {**row, "present": True, "constant": None}
                    for row in lookups.rows(view, view.entries)
                ]
                if not isinstance(view, ReviewedLevel):
                    continue
                held = {entry.entry_id for entry in view.entries}
                left_out = _left_out(self._parsed.levels[name])
                absent = tuple(entry for entry in view.rule.entries() if entry.entry_id not in held)
                rows += [
                    {**row, "present": False, "constant": left_out.get(entry.reference.address())}
                    for entry, row in zip(absent, lookups.rows(view, absent), strict=True)
                ]
        return _fields_frame(rows)

    def resolve(self, request: FieldRequest) -> Resolution:
        """Answer one explicit request in the first set that defines its key, and record it."""
        if request.key is None:
            return self._sets.first().resolve(request)
        return self._sets.defining(request.key)[0].resolve(request)

    def snapshot(self, catalog: str | None = None) -> ResolutionSnapshot:
        """Return one set's self-contained record of the bindings, fields and every lookup so
        far; the first set named by default."""
        return (self._sets.first() if catalog is None else self._sets.sets[catalog]).snapshot()


def _enforce(sets: tuple[_Lookups, ...], enforce: Enforce) -> None:
    """Check the named sets' requirements once, when the catalog opens; every missing field is
    recorded in its set's snapshot.

    Under ``"required"`` a missing recommended field is logged in one warning; under
    ``"recommended"`` it raises with the required ones.

    Raises:
        ValueError: ``enforce`` is set, but no named set has requirement rows.
        MissingRequiredField: Fields the sets require are missing, every one listed.
    """
    if enforce is None:
        return
    binding = [lookups for lookups in sets if lookups.catalogues.requirements]
    if not binding:
        names = [lookups.name for lookups in sets]
        raise ValueError(f"catalogues {names} set no requirements, so nothing to enforce")
    missing = [found for lookups in binding for found in lookups.missing()]
    raising = tuple(
        found for found in missing if enforce == "recommended" or found[1].requirement == "required"
    )
    warned = tuple(
        found for found in missing if enforce == "required" and found[1].requirement != "required"
    )
    if warned:
        _LOG.warning(str(MissingRequiredField(warned)))
    if raising:
        raise MissingRequiredField(raising)


def _data_lookups(
    levels: Mapping[str, LevelFields], metadata: Mapping[str, object], name: str
) -> _Lookups:
    """One set bound to every level of a result.

    Raises:
        ValueError: The set has no vendor catalogue, none of its apps has run on the result and
            the result records none of its annotation conventions, so it can answer nothing.
    """
    catalogues = catalogue_set(name)
    annotations = tuple(
        annotation for annotation in catalogues.annotations if annotation.applies(metadata)
    )
    _check_answers(name, catalogues, metadata, annotations)
    views: dict[str, LevelView] = {}
    for level_name, level in levels.items():
        software, pattern, rule_level = level.rule or (None, None, None)
        views[level_name] = level_view(
            level_name,
            software,
            pattern,
            rule_level,
            catalogues,
            retained=level.retained,
            obs_columns=level.obs_columns,
            ran=lambda producer: producer.ran(metadata),
            annotations=annotations,
        )
    return _Lookups(name, catalogues, views)


def _check_answers(
    name: str,
    catalogues: SourceCatalogues,
    metadata: Mapping[str, object],
    annotations: tuple[AnnotationCatalogue, ...],
) -> None:
    """Require a set without vendor catalogues to have a source the result answers from: an app
    that has run or an annotation convention the result records.

    Raises:
        ValueError: The set can answer nothing; the message says what to run.
    """
    if (
        catalogues.needs_review
        or annotations
        or any(producer.ran(metadata) for producer in catalogues.producers)
    ):
        return
    reasons = [producer.pending_reason() for producer in catalogues.producers]
    if catalogues.annotations:
        conventions = ", ".join(sorted(found.convention for found in catalogues.annotations))
        reasons.append(
            f"the result records no sample annotation ({conventions}); run apb2 annotate"
        )
    raise ValueError(
        f"{name}: {'; '.join(reasons) or 'no source of the set applies to the result'}"
    )


def _check_shared_keys(sets: Mapping[str, _Lookups]) -> None:
    """Require sets that share a key to name the same fields with it, level by level and slot by
    slot; a set may name more, told apart by a qualifier the other set lacks.

    Raises:
        ValueError: Two sets name different fields for one key in one slot of a level.
    """
    named: dict[tuple[str, str, Location], dict[str, set[Address]]] = {}
    for set_name, lookups in sets.items():
        for level, view in lookups.views.items():
            for entry in view.entries:
                location: Location = (
                    "var" if entry.reference.location == "varm" else entry.reference.location
                )
                slot = named.setdefault((level, entry.key, location), {})
                slot.setdefault(set_name, set()).add(entry.reference.address())
    for (level, key, location), by_set in named.items():
        fields = list(by_set.values())
        if any(not (one <= other or other <= one) for one in fields for other in fields):
            raise ValueError(
                f"key {key!r} names different {location} fields on {level} in the sets "
                f"{sorted(by_set)}"
            )


def _fields_frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame()
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(
        pl.col("constant").cast(pl.String)
    )


def _retained(level: ParsedLevel) -> set[Address]:
    retained: set[Address] = {("layers", None, layer) for layer in level.layers}
    retained |= {("var", None, column) for column in level.var.frame.columns}
    retained |= {("obs", None, column) for column in level.obs.frame.columns}
    retained |= {
        ("varm", table, column) for table, frame in level.varm.items() for column in frame.columns
    }
    return retained


def _left_out(level: ParsedLevel) -> dict[Address, str]:
    """The single value of each field APB2 left out of the level, by address."""
    result = level.uns.get("result")
    uninformative = result.get("uninformative_fields") if isinstance(result, dict) else None
    single = uninformative.get("single_valued") if isinstance(uninformative, dict) else None
    if not isinstance(single, dict):
        return {}
    found: dict[Address, str] = {}
    for location, fields in single.items():
        if not isinstance(fields, dict):
            continue
        for name, evidence in fields.items():
            value = evidence.get("value") if isinstance(evidence, dict) else None
            found[(cast(Location, location), None, name)] = json.dumps(value)
    return found


def _stored_rule(uns: Mapping[str, JsonValue]) -> dict[str, JsonValue] | None:
    provenance = uns.get("provenance")
    rule_json = provenance.get("rule_json") if isinstance(provenance, dict) else None
    return cast(dict[str, JsonValue], json.loads(rule_json)) if isinstance(rule_json, str) else None


def rule_version(level: ParsedLevel) -> tuple[str, str, str] | None:
    """Return the software name, version pattern and level a level's stored rule declares."""
    return stored_rule_version(level.uns)


def stored_rule_version(uns: Mapping[str, JsonValue]) -> tuple[str, str, str] | None:
    """Return the software name, version pattern and level the rule a level's parse metadata
    stores declares."""
    rule = _stored_rule(uns)
    if rule is None:
        return None
    software, version, rule_level = (
        rule.get(key)
        for key in ("software_name", "software_version_pattern", "quantification_level")
    )
    if isinstance(software, str) and isinstance(version, str) and isinstance(rule_level, str):
        return software, version, rule_level
    return None


def attach_snapshot(parsed: ParsedLevels, snapshot: ResolutionSnapshot) -> ParsedLevels:
    """Return a new result carrying the snapshot beside other catalogues' snapshots.

    The root record ``catalog.<catalogue>`` holds the snapshot as its ``result``; each level the
    snapshot answered a request for gets a record of the same name summarizing those requests.
    Scientific data is shared, not copied.
    """
    snapshots = _records(parsed.metadata)
    snapshots[snapshot.catalogue] = {"result": snapshot.model_dump(mode="json")}
    levels = {
        name: replace(level, metadata=_with_level_summary(level.metadata, name, snapshot))
        for name, level in parsed.levels.items()
    }
    return replace(parsed, levels=levels, metadata={**parsed.metadata, METADATA_KEY: snapshots})


def _records(metadata: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Return a copy of one part's records by catalogue; an absent namespace holds none.

    A present namespace that is not an object raises rather than being treated as absent, so
    attaching a snapshot never replaces evidence it cannot read.
    """
    if METADATA_KEY not in metadata:
        return {}
    namespace = metadata[METADATA_KEY]
    if not isinstance(namespace, dict):
        raise ValueError(
            f"metadata[{METADATA_KEY!r}] holds {type(namespace).__name__}, "
            "not snapshots by catalogue"
        )
    return dict(namespace)


def _with_level_summary(
    metadata: dict[str, JsonValue], level: str, snapshot: ResolutionSnapshot
) -> dict[str, JsonValue]:
    """One level's metadata with its count of resolved, missing and unresolved requests.

    A missing field the catalog's ``enforce`` check recorded but did not raise for, a recommended
    field under ``enforce="required"``, needs attention. A level the snapshot answered no request for keeps its
    metadata unchanged.
    """
    answered = [
        resolution for resolution in snapshot.resolutions if resolution.request.level == level
    ]
    statuses = Counter(resolution.status for resolution in answered)
    if not statuses:
        return metadata
    unresolved = statuses["ambiguous"] + statuses["unknown"]
    required = sum(resolution.requirement is not None for resolution in answered)
    counts = (
        ("resolved_requests", "Resolved catalogue requests", statuses["resolved"], "ok"),
        ("missing_requests", "Missing catalogue requests", statuses["missing"], "ok"),
        (
            "unresolved_requests",
            "Ambiguous or unknown catalogue requests",
            unresolved,
            "attention" if unresolved else "ok",
        ),
        (
            "missing_required_requests",
            "Missing fields the catalogue requires",
            required,
            "attention" if required else "ok",
        ),
    )
    summary: list[JsonValue] = [
        {"name": name, "label": label, "value": value, "unit": "requests", "status": status}
        for name, label, value, status in counts
    ]
    records = _records(metadata)
    records[snapshot.catalogue] = {"summary": summary}
    return {**metadata, METADATA_KEY: records}
