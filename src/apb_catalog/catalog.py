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
from apb2.api import FinalLayerTable, JsonValue, ParsedLevel, ParsedLevels

from apb_catalog import rules
from apb_catalog.resolver import (
    AbsentLevel,
    FieldRequest,
    LevelView,
    PendingEntry,
    ProducedLevel,
    Resolution,
    ReviewedLevel,
    UnreviewedLevel,
)
from apb_catalog.snapshot import ResolutionSnapshot, this_producer
from apb_catalog.source import (
    Address,
    AnnotationCatalogue,
    CatalogueDescription,
    Location,
    ProducerCatalogue,
    RequirementRow,
    SourceCatalogues,
    SourceEntry,
    catalogue_set,
)
from apb_catalog.source import Reference as SourceReference
from apb_catalog.table import entry_row

METADATA_KEY = "catalog"
_DEFAULTS = {"stage": "identification"}
_LOG = logging.getLogger("apb_catalog")

type Enforce = Literal["MUST", "SHOULD"] | None


@dataclass(frozen=True, slots=True)
class Reference:
    """Where a field with the asked meaning lives: level, location, column and ``varm`` table."""

    level: str
    location: Location
    name: str
    table: str | None = None

    @classmethod
    def of(cls, reference: SourceReference, /) -> Reference:
        """The public form of a bound catalogue reference."""
        return cls(
            level=reference.level,
            location=reference.location,
            name=reference.address()[2],
            table=reference.table,
        )


class MissingRequiredField(LookupError):
    """A field the set requires is absent from the rule or the result, under ``enforce``."""

    def __init__(self, resolution: Resolution, row: RequirementRow) -> None:
        wanted = ", ".join(
            f"{name}={'|'.join(values)}" for name, values in resolution.request.qualifiers.items()
        )
        super().__init__(
            f"{row.requirement} field {wanted} on {row.level} is missing: "
            f"{'; '.join(resolution.reasons)}"
        )
        self.resolution = resolution
        self.row = row


class StaleField(LookupError):
    """A field the result's stored rule declares differently from the current packaged rule."""

    def __init__(self, reference: SourceReference, stored: str, current: str) -> None:
        super().__init__(
            f"{reference.name}: this result reads {stored}, the current rule {current}; reconvert"
        )
        self.reference = reference


def _bind(
    entry: SourceEntry, roles: Mapping[str, str], obs_columns: tuple[str, ...]
) -> tuple[SourceEntry, ...]:
    """The entry bound to the level's column: by name, by the role's column or by prefix.

    A prefix matching several columns binds to each, so the lookup reports them as ambiguous.
    """
    reference = entry.reference
    if reference.role is not None:
        column = roles.get(reference.role)
        return () if column is None else (entry.bound(column),)
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
    roles: Mapping[str, str],
    obs_columns: tuple[str, ...] = (),
    ran: Callable[[ProducerCatalogue], bool],
    annotations: tuple[AnnotationCatalogue, ...] = (),
) -> LevelView:
    """Bind one level to its set: the reviewed vendor entries, then APB's own fields.

    Only entries whose field the level holds answer; a producer that has not run leaves its
    entries pending. A set with vendor catalogues answers only for a reviewed rule.
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
            for bound in _bind(entry, roles, obs_columns)
        ]
        if ran(producer):
            entries += [entry for entry in offered if entry.reference.address() in retained]
        else:
            pending += [PendingEntry(entry, producer.pending_reason()) for entry in offered]
    for annotation in annotations:
        entries += [
            bound
            for entry in annotation.entries_on(rule_level)
            for bound in _bind(entry, roles, obs_columns)
        ]
    if reviewed is not None:
        return ReviewedLevel(name, reviewed, tuple(entries), tuple(pending))
    return ProducedLevel(name, software, pattern, tuple(entries), tuple(pending))


class _Lookups:
    """The requests, answers and snapshot both catalogues share for one set."""

    __slots__ = ("catalogues", "enforce", "name", "resolutions", "views")

    def __init__(
        self, name: str, catalogues: SourceCatalogues, views: dict[str, LevelView], enforce: Enforce
    ) -> None:
        if enforce is not None and not catalogues.requirements:
            raise ValueError(f"catalogue {name!r} sets no requirements, so nothing to enforce")
        self.name = name
        self.catalogues = catalogues
        self.views = views
        self.enforce = enforce
        self.resolutions: list[Resolution] = []

    def request(
        self, level: str, location: Location, qualifiers: Mapping[str, str]
    ) -> FieldRequest:
        declared = self.catalogues.vocabulary.qualifiers
        described = {name: value for name, value in _DEFAULTS.items() if name in declared}
        described |= qualifiers
        return FieldRequest(
            level=level,
            location=location,
            qualifiers={name: (value,) for name, value in described.items()},
        )

    def answer(self, request: FieldRequest) -> Resolution:
        self.catalogues.vocabulary.check_predicate(request.qualifiers)
        return self.views.get(request.level, AbsentLevel(request.level)).resolve(request)

    def resolve(self, request: FieldRequest) -> Resolution:
        resolution = self.answer(request)
        self.resolutions.append(resolution)
        return resolution

    def find(
        self, level: str, location: Location, qualifiers: Mapping[str, str]
    ) -> SourceReference | None:
        """The field asked for; a missing required field raises or warns as ``enforce`` says."""
        request = self.request(level, location, qualifiers)
        resolution = self.answer(request)
        row = (
            self.catalogues.requirement_for(level, location, request.qualifiers)
            if resolution.status == "missing" and self.enforce is not None
            else None
        )
        if row is None or row.requirement == "MAY":
            self.resolutions.append(resolution)
            return resolution.found()
        resolution = resolution.model_copy(update={"requirement": row.requirement})
        self.resolutions.append(resolution)
        if row.requirement == "MUST" or self.enforce == "SHOULD":
            raise MissingRequiredField(resolution, row)
        _LOG.warning(str(MissingRequiredField(resolution, row)))
        return None

    def kinds(
        self, level: str, location: Location, qualifiers: Mapping[str, str]
    ) -> tuple[str, ...]:
        return self.answer(self.request(level, location, qualifiers)).offered("kind")

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
        labels = {
            entry.entry_id: source.label
            for source in self.catalogues.sources()
            for entry in source.entries
        }
        return [
            entry_row(
                self.name,
                self.catalogues,
                labels[entry.entry_id],
                binding.software_version_pattern,
                (_view_rule(view) or "*") if entry.rules else "*",
                entry,
            )
            for entry in entries
        ]


def _view_rule(view: LevelView) -> str | None:
    return view.rule.variant.rule if isinstance(view, ReviewedLevel) else None


class Catalog:
    """Which column one software version reports for each meaning, without any data.

    ``Catalog("DIA-NN", "2.6.0", "abundance").layer("peptidoform_ion", kind="intensity").name``
    is ``'Precursor_Quantity'``. The software's packaged APB2 rule
    whose version pattern admits ``version`` decides which fields each level has.

    Raises:
        ValueError: No packaged rule of the software admits the version.
    """

    __slots__ = ("_lookups",)

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
                retained=rules.retained(found.rule, found.level),
                roles=rules.roles(found.rule, found.level),
                ran=lambda producer: not producer.requires,
            )
        self._lookups = _Lookups(catalog, catalogues, views, enforce)

    @property
    def description(self) -> CatalogueDescription:
        """What this catalogue set holds and who uses it."""
        return self._lookups.catalogues.description

    def kinds(self, level: str, location: Location, **qualifiers: str) -> tuple[str, ...]:
        """The kinds the level offers at one location, given the other qualifiers."""
        return self._lookups.kinds(level, location, qualifiers)

    def layer(self, level: str, kind: str, **qualifiers: str) -> Reference | None:
        """Where the sample-by-feature layer with this meaning lives, or ``None``."""
        return self._found(level, "layers", kind, qualifiers)

    def var(self, level: str, kind: str, **qualifiers: str) -> Reference | None:
        """Where the per-feature column with this meaning lives, in ``var`` or a ``varm`` table."""
        return self._found(level, "var", kind, qualifiers)

    def obs(self, level: str, kind: str, **qualifiers: str) -> Reference | None:
        """Where the per-sample column with this meaning lives, or ``None``."""
        return self._found(level, "obs", kind, qualifiers)

    def fields(self) -> pl.DataFrame:
        """Every catalogued field the rule declares, one row per field, as ``apb-catalog table``
        shows them, with ``present`` true for each."""
        rows = [
            {**row, "present": True, "constant": None}
            for view in self._lookups.views.values()
            for row in self._lookups.rows(view, view.entries)
        ]
        return _fields_frame(rows)

    def _found(
        self, level: str, location: Location, kind: str, qualifiers: Mapping[str, str]
    ) -> Reference | None:
        found = self._lookups.find(level, location, {"kind": kind, **qualifiers})
        return None if found is None else Reference.of(found)


class DataCatalog:
    """What one APB result's fields mean to one consumer, with the data handed back directly.

    ``DataCatalog(result, "confidence").layer("peptidoform_ion", kind="pep")`` returns MaxQuant's
    ``PEP`` or Spectronaut's ``EG_PEP`` layer, or ``None`` when the vendor reports no PEP or APB2
    left it out because it held one value or none. Confidence lookups mean identification unless
    ``stage="quantification"`` says otherwise. Ambiguous or unreviewed answers raise
    :class:`~apb_catalog.resolver.UnresolvedField`; a field the result's stored rule declares
    differently from the current packaged rule raises :class:`StaleField`.
    """

    __slots__ = ("_lookups", "_parsed")

    def __init__(self, result: ParsedLevels, catalog: str, enforce: Enforce = None) -> None:
        self._parsed = result
        catalogues = catalogue_set(catalog)
        annotations = tuple(
            annotation
            for annotation in catalogues.annotations
            if annotation.applies(result.metadata)
        )
        views: dict[str, LevelView] = {}
        for name, level in result.levels.items():
            software, pattern, rule_level = rule_version(level) or (None, None, None)
            views[name] = level_view(
                name,
                software,
                pattern,
                rule_level,
                catalogues,
                retained=_retained(level),
                roles=level.var.roles,
                obs_columns=tuple(level.obs.frame.columns),
                ran=lambda producer: producer.ran(result.metadata),
                annotations=annotations,
            )
        self._lookups = _Lookups(catalog, catalogues, views, enforce)

    @property
    def description(self) -> CatalogueDescription:
        """What this catalogue set holds and who uses it."""
        return self._lookups.catalogues.description

    def kinds(self, level: str, location: Location, **qualifiers: str) -> tuple[str, ...]:
        """The kinds the level offers at one location, given the other qualifiers."""
        return self._lookups.kinds(level, location, qualifiers)

    def layer(self, level: str, kind: str, **qualifiers: str) -> FinalLayerTable | None:
        """Return the sample-by-feature layer with this meaning, or ``None``."""
        reference = self._find(level, "layers", kind, qualifiers)
        return (
            None if reference is None else self._parsed.levels[level].layers[reference.address()[2]]
        )

    def var(self, level: str, kind: str, **qualifiers: str) -> pl.Series | None:
        """Return the per-feature column with this meaning, from ``var`` or a ``varm`` table."""
        reference = self._find(level, "var", kind, qualifiers)
        if reference is None:
            return None
        found = self._parsed.levels[level]
        name = reference.address()[2]
        if reference.table is None:
            return found.var.frame[name]
        return found.varm[reference.table][name]

    def obs(self, level: str, kind: str, **qualifiers: str) -> pl.Series | None:
        """Return the per-sample column with this meaning, or ``None``."""
        reference = self._find(level, "obs", kind, qualifiers)
        return (
            None
            if reference is None
            else self._parsed.levels[level].obs.frame[reference.address()[2]]
        )

    def fields(self) -> pl.DataFrame:
        """Every catalogued field of the result, one row per field, as ``apb-catalog table``
        shows them, with ``present`` and, for a field APB2 left out because it held one value,
        that ``constant``."""
        rows: list[dict[str, object]] = []
        for name, view in self._lookups.views.items():
            rows += [
                {**row, "present": True, "constant": None}
                for row in self._lookups.rows(view, view.entries)
            ]
            if not isinstance(view, ReviewedLevel):
                continue
            held = {entry.entry_id for entry in view.entries}
            left_out = _left_out(self._parsed.levels[name])
            absent = tuple(entry for entry in view.rule.entries() if entry.entry_id not in held)
            rows += [
                {**row, "present": False, "constant": left_out.get(entry.reference.address())}
                for entry, row in zip(absent, self._lookups.rows(view, absent), strict=True)
            ]
        return _fields_frame(rows)

    def resolve(self, request: FieldRequest) -> Resolution:
        """Answer one explicit request and record it for the snapshot."""
        return self._lookups.resolve(request)

    def snapshot(self) -> ResolutionSnapshot:
        """Return a self-contained record of the bindings, fields and every lookup so far."""
        return self._lookups.snapshot()

    def _find(
        self, level: str, location: Location, kind: str, qualifiers: Mapping[str, str]
    ) -> SourceReference | None:
        reference = self._lookups.find(level, location, {"kind": kind, **qualifiers})
        if reference is not None:
            self._check_current(level, reference)
        return reference

    def _check_current(self, level: str, reference: SourceReference) -> None:
        """Raise when the stored rule declares the field differently from the current rule."""
        view = self._lookups.views[level]
        rule = _view_rule(view)
        stored_rule = _stored_rule(self._parsed.levels[level])
        if rule is None or stored_rule is None:
            return
        location, _, name = reference.address()
        stored = rules.field(stored_rule, location, name)
        rule_level = cast(str, stored_rule["quantification_level"])
        current = [
            rules.field(declared, location, name)
            for declared in rules.declarations(rule, rule_level)
        ]
        if stored in current or (stored is None and not any(current)):
            return
        declared = next((found for found in current if found is not None), None)
        raise StaleField(reference, _source_of(stored), _source_of(declared))


def _source_of(declared: dict[str, JsonValue] | None) -> str:
    if declared is None:
        return "no such field"
    source = declared.get("source") or declared.get("inputs")
    return json.dumps(source) if source is not None else json.dumps(declared, sort_keys=True)


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


def _stored_rule(level: ParsedLevel) -> dict[str, JsonValue] | None:
    provenance = level.uns.get("provenance")
    rule_json = provenance.get("rule_json") if isinstance(provenance, dict) else None
    return cast(dict[str, JsonValue], json.loads(rule_json)) if isinstance(rule_json, str) else None


def rule_version(level: ParsedLevel) -> tuple[str, str, str] | None:
    """Return the software name, version pattern and level a level's stored rule declares."""
    rule = _stored_rule(level)
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


def stored_snapshot(parsed: ParsedLevels, catalogue: str) -> ResolutionSnapshot | None:
    """Return the snapshot one catalogue set left on a result, if any."""
    snapshots = _records(parsed.metadata)
    if catalogue not in snapshots:
        return None
    record = snapshots[catalogue]
    return ResolutionSnapshot.model_validate(
        record.get("result") if isinstance(record, dict) else record
    )


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

    A missing field the lookup required but did not raise for, a SHOULD field under
    ``enforce="MUST"``, needs attention. A level the snapshot answered no request for keeps its
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


def stale_levels(parsed: ParsedLevels, snapshot: ResolutionSnapshot) -> tuple[str, ...]:
    """Return the snapshot's levels whose current software or version differs from the recorded."""
    return tuple(
        binding.level
        for binding in snapshot.levels
        if binding.level not in parsed.levels
        or _software_version(parsed.levels[binding.level])
        != (binding.software_name, binding.software_version_pattern)
    )


def _software_version(level: ParsedLevel) -> tuple[str | None, str | None]:
    version = rule_version(level)
    return (None, None) if version is None else (version[0], version[1])
