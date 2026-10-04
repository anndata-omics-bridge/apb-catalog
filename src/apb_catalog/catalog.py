"""Look up an APB result's fields by meaning, so callers never name vendor columns."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import overload

import polars as pl
from apb2.api import FinalLayerTable, ParsedLevel, ParsedLevels

from apb_catalog.fingerprint import fingerprint
from apb_catalog.resolver import (
    AbsentLevel,
    ConceptRequest,
    Resolution,
    ReviewedLevel,
    UnreviewedLevel,
)
from apb_catalog.snapshot import ResolutionSnapshot, this_producer
from apb_catalog.source import (
    CatalogueDescription,
    Location,
    Reference,
    SourceCatalogues,
    packaged_catalogues,
)

METADATA_KEY = "catalog"
_DEFAULTS = {"stage": "identification"}


class Catalog:
    """What one APB result's fields mean to one consumer, with the data handed back directly.

    ``Catalog(parsed, "identification_confidence").layer("ion", concept="confidence", kind="pep")`` returns
    MaxQuant's ``PEP`` or Spectronaut's ``EG_PEP`` layer, or ``None`` when the vendor reports no
    PEP; ``Catalog(parsed, "miape").var("protein", concept="miape", kind="gene_name")`` returns the
    column MIAPE-AnnData calls ``gene_name``. Leaving out ``kind`` lists the kinds the level holds.
    A level answers only for its own entity. Confidence lookups mean identification unless
    ``stage="quantification"`` says otherwise. Ambiguous or unreviewed answers raise
    :class:`~apb_catalog.resolver.UnresolvedField` naming the candidates.
    """

    __slots__ = ("_catalogues", "_name", "_parsed", "_resolutions", "_views")

    def __init__(self, parsed: ParsedLevels, catalogue: str) -> None:
        self._parsed = parsed
        self._name = catalogue
        self._catalogues = packaged_catalogues(catalogue)
        self._views: dict[str, ReviewedLevel | UnreviewedLevel] = {
            name: level_view(name, level, self._catalogues) for name, level in parsed.levels.items()
        }
        self._resolutions: list[Resolution] = []

    @property
    def description(self) -> CatalogueDescription:
        """What this catalogue set holds and who uses it."""
        return self._catalogues.description

    @overload
    def layer(
        self, level: str, concept: str, kind: str, **qualifiers: str
    ) -> FinalLayerTable | None: ...

    @overload
    def layer(
        self, level: str, concept: str, kind: None = None, **qualifiers: str
    ) -> tuple[str, ...] | None: ...

    def layer(
        self, level: str, concept: str, kind: str | None = None, **qualifiers: str
    ) -> FinalLayerTable | tuple[str, ...] | None:
        """Return the sample-by-feature layer with this meaning, or the kinds on offer."""
        if kind is None:
            return self._kinds(level, "layers", concept, qualifiers)
        reference = self._find(level, "layers", concept, qualifiers | {"kind": kind})
        return None if reference is None else self._parsed.levels[level].layers[reference.name]

    @overload
    def var(self, level: str, concept: str, kind: str, **qualifiers: str) -> pl.Series | None: ...

    @overload
    def var(
        self, level: str, concept: str, kind: None = None, **qualifiers: str
    ) -> tuple[str, ...] | None: ...

    def var(
        self, level: str, concept: str, kind: str | None = None, **qualifiers: str
    ) -> pl.Series | tuple[str, ...] | None:
        """Return the per-feature column with this meaning, or the kinds on offer."""
        if kind is None:
            return self._kinds(level, "var", concept, qualifiers)
        reference = self._find(level, "var", concept, qualifiers | {"kind": kind})
        return None if reference is None else self._parsed.levels[level].var.frame[reference.name]

    def fields(self) -> pl.DataFrame:
        """List every catalogued field the result retains, one row per field."""
        return pl.DataFrame(
            [
                {
                    "level": entry.reference.level,
                    "location": entry.reference.location,
                    "name": entry.reference.name,
                    "concept": entry.concept,
                    **entry.qualifiers,
                }
                for view in self._views.values()
                for entry in view.entries
            ]
        )

    def resolve(self, request: ConceptRequest) -> Resolution:
        """Answer one explicit request and record it for the snapshot."""
        resolution = self._answer(request)
        self._resolutions.append(resolution)
        return resolution

    def snapshot(self) -> ResolutionSnapshot:
        """Return a self-contained record of the bindings, fields and every lookup so far."""
        entries = tuple(entry for view in self._views.values() for entry in view.entries)
        concepts = {entry.concept for entry in entries}
        concepts |= {resolution.request.concept for resolution in self._resolutions}
        vocabulary = self._catalogues.vocabulary
        return ResolutionSnapshot(
            producer=this_producer(),
            catalogue=self._name,
            description=self._catalogues.description,
            vocabulary_version=vocabulary.vocabulary_version,
            concepts={name: vocabulary.concept(name) for name in sorted(concepts)},
            levels=tuple(view.binding() for view in self._views.values()),
            entries=entries,
            resolutions=tuple(self._resolutions),
        )

    def _find(
        self,
        level: str,
        location: Location,
        concept: str,
        qualifiers: dict[str, str],
    ) -> Reference | None:
        return self.resolve(self._request(level, location, concept, qualifiers)).found()

    def _kinds(
        self,
        level: str,
        location: Location,
        concept: str,
        qualifiers: dict[str, str],
    ) -> tuple[str, ...] | None:
        offered = self._answer(self._request(level, location, concept, qualifiers)).offered("kind")
        return offered or None

    def _request(
        self,
        level: str,
        location: Location,
        concept: str,
        qualifiers: dict[str, str],
    ) -> ConceptRequest:
        declared = self._catalogues.vocabulary.concept(concept).qualifiers
        described = {name: value for name, value in _DEFAULTS.items() if name in declared}
        described |= qualifiers
        return ConceptRequest(
            concept=concept,
            level=level,
            location=location,
            qualifiers={name: (value,) for name, value in described.items()},
        )

    def _answer(self, request: ConceptRequest) -> Resolution:
        self._catalogues.vocabulary.concept(request.concept).check_predicate(request.qualifiers)
        return self._views.get(request.level, AbsentLevel(request.level)).resolve(request)


def rule_fingerprint(level: ParsedLevel, /) -> str | None:
    """Return the fingerprint of a level's stored effective rule, if it records one."""
    rule_json = level.uns.get("rule_json")
    if not isinstance(rule_json, str):
        return None
    return fingerprint(json.loads(rule_json))


def level_view(
    name: str, level: ParsedLevel, catalogues: SourceCatalogues, /
) -> ReviewedLevel | UnreviewedLevel:
    """Bind one level to its reviewed rule, keeping only entries whose fields it retains."""
    level_fingerprint = rule_fingerprint(level)
    if level_fingerprint is None:
        return UnreviewedLevel(name, None, "the level records no rule_json provenance")
    reviewed = catalogues.reviewed(level_fingerprint)
    if reviewed is None:
        return UnreviewedLevel(
            name, level_fingerprint, "no source catalogue reviewed this effective rule"
        )
    retained = {("layers", layer) for layer in level.layers}
    retained |= {("var", column) for column in level.var.frame.columns}
    entries = tuple(
        entry
        for entry in reviewed.entries()
        if (entry.reference.location, entry.reference.name) in retained
    )
    return ReviewedLevel(name, level_fingerprint, reviewed, entries)


def attach_snapshot(parsed: ParsedLevels, snapshot: ResolutionSnapshot) -> ParsedLevels:
    """Return a new result carrying the snapshot beside other catalogues' snapshots.

    Scientific data is shared, not copied.
    """
    namespace = parsed.metadata.get(METADATA_KEY)
    snapshots = dict(namespace) if isinstance(namespace, dict) else {}
    snapshots[snapshot.catalogue] = snapshot.model_dump(mode="json")
    return replace(parsed, metadata={**parsed.metadata, METADATA_KEY: snapshots})


def stored_snapshot(parsed: ParsedLevels, catalogue: str) -> ResolutionSnapshot | None:
    """Return the snapshot one catalogue set left on a result, if any."""
    namespace = parsed.metadata.get(METADATA_KEY)
    stored = namespace.get(catalogue) if isinstance(namespace, dict) else None
    if stored is None:
        return None
    return ResolutionSnapshot.model_validate(stored)


def stale_levels(parsed: ParsedLevels, snapshot: ResolutionSnapshot) -> tuple[str, ...]:
    """Return the snapshot's levels whose current effective rule differs from the recorded one."""
    return tuple(
        binding.level
        for binding in snapshot.levels
        if binding.level not in parsed.levels
        or rule_fingerprint(parsed.levels[binding.level]) != binding.fingerprint
    )
