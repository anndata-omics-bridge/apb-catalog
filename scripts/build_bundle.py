"""Build the bundle other languages implement apb-catalog on: rules, catalogues, expected answers.

``make bundle`` writes ``build/apb-catalog-bundle/`` and ``build/apb-catalog-bundle.tar.gz``. The
release workflow attaches the archive to the GitHub release and copies the folder into apbCatalogR.

The bundle holds APB2's effective rule declarations, the packaged catalogue sets with their
schemas, synthetic Parquet results built from the declarations (packed in ``results.tar.gz``), and
the answers this package gives on them. Only packaged sets enter; an installed plugin set never does.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Callable, Iterator, Mapping
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import cast, override

import polars as pl
from apb2.api import (
    FIXED_COLUMNS,
    JsonValue,
    ParsedLevel,
    ParsedLevels,
    packaged_rule_declarations,
    write_parsed_levels,
)
from pydantic import TypeAdapter

from apb_catalog import rules
from apb_catalog.catalog import (
    Catalog,
    DataCatalog,
    Enforce,
    MissingRequiredField,
    Reference,
    StaleField,
)
from apb_catalog.coverage import CATALOGUES_SCHEMA, VERSION_LABELS, coverage_of
from apb_catalog.resolver import UnresolvedField
from apb_catalog.source import (
    AnnotationCatalogue,
    CatalogueDescription,
    Location,
    ProducerCatalogue,
    RequirementRow,
    SourceCatalogue,
    SourceCatalogues,
    packaged_catalogues,
    packaged_descriptions,
)
from apb_catalog.table import KEY_COLUMNS, schema, set_rows
from apb_catalog.vocabulary import Vocabulary

NAME = "apb-catalog-bundle"
BUNDLE_FORMAT = 1
"""Raised when a reader of the previous format could not read the bundle."""

LEVELS = ("protein", "peptide", "peptidoform", "peptidoform_ion", "peptidoform_fragment")

SAMPLE_VERSIONS: dict[str, str] = {
    "^2\\.": "2.2.0",
    "^2\\..*": "2.2.0",
    "^1\\.": "1.4.0",
    "^1\\..*": "1.4.0",
    "^v?1\\..*": "1.4.0",
    "^0\\.": "0.4.0",
    "^0\\.5\\.": "0.5.1",
    "^.*$": "1.0",
    "^13(?:\\.|\\s|$)": "13.0",
    "^1\\.[0-7](\\.|$)": "1.7",
    "^1\\.[89](\\.|$)": "1.8.1",
    "^1\\.10(?:\\.|-|$)": "1.10.0",
    "^1\\.12(?:\\.|-|$)": "1.12.0",
    "^2[23]\\.": "22.0",
    "^(1\\.5|1\\.6|2\\.)": "2.0.1",
    "^(19|20)\\..*": "19.0",
    "^15\\..*": "15.7",
    "^21\\..*": "21.0",
    "^0\\.9\\.11$": "0.9.11",
}
"""One software version each rule's version pattern admits, to construct a ``Catalog`` with."""

type Declaration = dict[str, JsonValue]
type Request = tuple[str, Location, dict[str, str]]


def main(argv: list[str]) -> int:
    """Build the bundle folder and its archive under ``argv[1]``, ``build`` by default."""
    target = Path(argv[1]) if len(argv) > 1 else Path("build")
    folder = build(target / NAME)
    with tarfile.open(target / f"{NAME}.tar.gz", "w:gz") as archive:
        archive.add(folder, arcname=NAME)
    print(f"wrote {folder} and {target / f'{NAME}.tar.gz'}")
    return 0


def build(folder: Path) -> Path:
    """Write the bundle into ``folder``, replacing what is there."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    names = list(packaged_descriptions())
    _write_rules(folder / "rules")
    _write_catalogues(folder / "catalogues", names)
    _write_schemas(folder / "schemas")
    results = synthetic_results()
    _write_results(folder / "results.tar.gz", results)
    sets = {name: packaged_catalogues(name) for name in names}
    _write_json(folder / "cases" / "catalog.json", catalog_cases(sets))
    _write_json(folder / "cases" / "data_catalog.json", data_catalog_cases(sets, results))
    _write_json(folder / "cases" / "tables.json", table_cases(sets))
    files = sorted(
        path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()
    )
    manifest: dict[str, JsonValue] = {
        "bundle_format": BUNDLE_FORMAT,
        "version": metadata.version("apb-catalog"),
        "apb_catalog_version": metadata.version("apb-catalog"),
        "apb2_version": metadata.version("apb2"),
        "catalogues": list(names),
        "files": list(files),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")
    return folder


def _write_results(archive: Path, results: Mapping[str, ParsedLevels]) -> None:
    """The synthetic results in one archive: their Parquet paths exceed the 100 bytes R packages allow."""
    with tempfile.TemporaryDirectory() as scratch:
        for result, parsed in results.items():
            write_parsed_levels(parsed, Path(scratch) / f"{result}.parquet")
        with tarfile.open(archive, "w:gz", format=tarfile.GNU_FORMAT) as packed:
            for path in sorted(Path(scratch).iterdir()):
                packed.add(path, arcname=path.name)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n", "utf-8")


def _write_rules(folder: Path) -> None:
    """The effective declarations in APB2's order, and the version labels coverage prints."""
    declarations = [
        {"rule": rule, "level": level, "declarations": list(texts)}
        for (rule, level), texts in packaged_rule_declarations().items()
    ]
    _write_json(folder / "declarations.json", declarations)
    _write_json(folder / "version_labels.json", VERSION_LABELS)


def _write_catalogues(folder: Path, names: list[str]) -> None:
    """The packaged catalogue files as shipped, after loading each set checks them."""
    data = resources.files("apb_catalog").joinpath("data")
    for name in ("catalogues.json", "vocabulary.json", "requirements.json"):
        _copy(data.joinpath(name), folder / name)
    for name in names:
        packaged_catalogues(name)
        for kind in ("sources", "producers", "annotations"):
            directory = data.joinpath(kind, name)
            if not directory.is_dir():
                continue
            for path in directory.iterdir():
                if path.name.endswith(".json"):
                    _copy(path, folder / kind / name / path.name)


def _copy(source: Traversable, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text("utf-8"), "utf-8")


def _write_schemas(folder: Path) -> None:
    """JSON Schemas of every catalogue file the bundle carries."""
    schemas: dict[str, dict[str, object]] = {
        "catalogues": TypeAdapter(dict[str, CatalogueDescription]).json_schema(),
        "vocabulary": Vocabulary.model_json_schema(),
        "requirements": TypeAdapter(dict[str, tuple[RequirementRow, ...]]).json_schema(),
        "source-catalogue": SourceCatalogue.model_json_schema(),
        "producer-catalogue": ProducerCatalogue.model_json_schema(),
        "annotation-catalogue": AnnotationCatalogue.model_json_schema(),
    }
    folder.mkdir(parents=True)
    for name, found in schemas.items():
        (folder / f"{name}.schema.json").write_text(json.dumps(found, indent=2) + "\n", "utf-8")


# Synthetic results ---------------------------------------------------------------------------

SAMPLES = 2
FEATURES = 3


def synthetic_results() -> dict[str, ParsedLevels]:
    """One result per packaged rule level, stored as conversion stores it, and the edge cases."""
    found: dict[str, ParsedLevels] = {}
    for rule, level in packaged_rule_declarations():
        found[_result_name(rule, level)] = ParsedLevels(
            levels={level: synthetic_level(rule, level)}, uns={}
        )
    found |= _edge_results()
    return found


def _result_name(rule: str, level: str) -> str:
    return f"{rule.removesuffix('/rules.json').replace('/', '_')}-{level}"


def synthetic_level(
    rule: str,
    level: str,
    rule_json: str | None = None,
    obs_extra: Mapping[str, list[str]] | None = None,
    stored: bool = True,
) -> ParsedLevel:
    """Two samples and three features with every field the rule level's first declaration keeps.

    The var frame also holds the APB2 columns the producer catalogue names on the level, as a
    converted result does. ``stored=False`` leaves out ``rule_json``.
    """
    declared = rules.declaration(rule, level)
    axis = cast(dict[str, list[str]], declared["axis"])
    columns = cast(dict[str, list[dict[str, JsonValue]]], declared["columns"])
    obs: dict[str, list[object]] = {
        key: [f"S{i}" for i in range(SAMPLES)] for key in axis["obs_keys"]
    }
    for column in columns.get("obs", []):
        obs.setdefault(str(column["name"]), _values(str(column["type"]), SAMPLES))
    obs |= {name: list(values) for name, values in (obs_extra or {}).items()}
    var: dict[str, list[object]] = {
        key: [f"F{i}" for i in range(FEATURES)] for key in axis["var_keys"]
    }
    for column in columns.get("var", []):
        var.setdefault(str(column["name"]), _values(str(column["type"]), FEATURES))
    for name in _producer_columns(level):
        var.setdefault(name, _values("boolean" if name.startswith("is_") else "string", FEATURES))
    abundance: dict[str, pl.DataFrame] = {}
    auxiliary: dict[str, pl.DataFrame] = {}
    measurements = cast(dict[str, list[dict[str, JsonValue]]], declared["measurements"])
    for offset, layer in enumerate(measurements["layers"]):
        if layer.get("encoding_mode") == "factor":
            continue
        values = _layer(offset, integer=layer.get("type") == "integer")
        roles = cast(list[str], layer.get("roles") or [])
        (abundance if "abundance" in roles else auxiliary)[str(layer["name"])] = values
    uns: dict[str, JsonValue] = {}
    if stored:
        text = rule_json or packaged_rule_declarations()[(rule, level)][0]
        uns["provenance"] = {"rule_json": text}
    return ParsedLevel.build(
        pl.DataFrame(obs),
        axis["obs_keys"],
        pl.DataFrame(var),
        axis["var_keys"],
        rules.roles(rule, level),
        primary_layer=next(iter(abundance)),
        abundance=abundance,
        auxiliary=auxiliary,
        uns=uns,
    )


def _values(kind: str, size: int) -> list[object]:
    if kind == "boolean":
        return [index % 2 == 0 for index in range(size)]
    if kind == "integer":
        return list(range(1, size + 1))
    if kind == "number":
        return [index + 0.5 for index in range(size)]
    return [f"v{index}" for index in range(size)]


def _layer(offset: int, integer: bool) -> pl.DataFrame:
    return pl.DataFrame(
        {
            f"c{sample}": [
                (offset + sample + feature) if integer else (offset + sample + feature) / 10
                for feature in range(FEATURES)
            ]
            for sample in range(SAMPLES)
        }
    )


def _producer_columns(level: str) -> list[str]:
    """The APB2 columns the packaged producer catalogues name on one level."""
    found: list[str] = []
    for name in packaged_descriptions():
        for producer in packaged_catalogues(name).producers:
            for entry in producer.entries_on(level):
                column = entry.reference.name
                if column in FIXED_COLUMNS and column not in found:
                    found.append(column)
    return found


MAXQUANT = "maxquant_wide/rules.json"
DIANN = "diann/v2/rules.json"


def _edge_results() -> dict[str, ParsedLevels]:
    """Results that exercise an unreviewed level, a stale field and both annotation conventions."""
    ion = "peptidoform_ion"
    stale = cast(dict[str, JsonValue], json.loads(packaged_rule_declarations()[(MAXQUANT, ion)][0]))
    measurements = cast(dict[str, list[dict[str, JsonValue]]], stale["measurements"])
    for layer in measurements["layers"]:
        if layer["name"] == "PEP":
            layer["source"] = "^evidence\\.Changed PEP (?P<sample>.+)$"
    two_levels = {level: synthetic_level(DIANN, level) for level in (ion, "protein")}
    return {
        "edge-unreviewed": _one(ion, synthetic_level(MAXQUANT, ion, stored=False)),
        "edge-stale": _one(ion, synthetic_level(MAXQUANT, ion, rule_json=json.dumps(stale))),
        "edge-sdrf": _one(
            ion,
            synthetic_level(
                DIANN,
                ion,
                obs_extra={
                    "factor_value_treatment": ["a", "b"],
                    "factor_value_dose": ["1", "2"],
                    "characteristics_biological_replicate": ["1", "2"],
                },
            ),
            {"sdrf": {}},
        ),
        "edge-prolfquapp": _one(
            ion,
            synthetic_level(DIANN, ion, obs_extra={"group": ["A", "B"], "subject": ["s1", "s2"]}),
            {"prolfquapp": {}},
        ),
        "edge-two-levels": ParsedLevels(levels=two_levels, uns={}),
    }


def _one(
    level: str, parsed: ParsedLevel, found: dict[str, JsonValue] | None = None
) -> ParsedLevels:
    return ParsedLevels(levels={level: parsed}, uns={}, metadata=found or {})


# Expected answers ----------------------------------------------------------------------------


class _Warnings(logging.Handler):
    """Collects the warnings a lookup logs for a missing field it does not raise for."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _reference(found: Reference) -> dict[str, JsonValue]:
    return {
        "level": found.level,
        "location": found.location,
        "table": found.table,
        "name": found.name,
    }


def _outcome(answer: Callable[[], Reference | None]) -> dict[str, JsonValue]:
    """What one lookup gives: a reference, ``null``, or the class of the error it raises."""
    handler = _Warnings()
    logger = logging.getLogger("apb_catalog")
    logger.addHandler(handler)
    try:
        found = answer()
    except UnresolvedField as error:
        return {"error": "UnresolvedField", "status": error.resolution.status}
    except (StaleField, MissingRequiredField) as error:
        return {"error": type(error).__name__}
    finally:
        logger.removeHandler(handler)
    outcome: dict[str, JsonValue] = {"reference": None if found is None else _reference(found)}
    if handler.records:
        outcome["warning"] = "MissingRequiredField"
    return outcome


def _kinds(answer: Callable[[], tuple[str, ...]]) -> dict[str, JsonValue]:
    try:
        return {"kinds": list(answer())}
    except UnresolvedField as error:
        return {"error": "UnresolvedField", "status": error.resolution.status}


def requests(sources: SourceCatalogues, level: str) -> list[Request]:
    """Every request a set's entries and requirement rows on one level ask, without repeats.

    Each entry asks once with all its qualifiers and once with its kind alone.
    """
    found: dict[str, Request] = {}

    def add(location: Location, qualifiers: dict[str, str]) -> None:
        key = json.dumps([location, qualifiers], sort_keys=True)
        found.setdefault(key, (level, location, qualifiers))

    for source in sources.sources():
        for entry in source.entries:
            if entry.reference.level != level:
                continue
            location: Location = (
                "var" if entry.reference.location == "varm" else entry.reference.location
            )
            add(location, dict(entry.qualifiers))
            add(location, {"kind": entry.qualifiers["kind"]})
    for row in sources.requirements:
        if row.level == level:
            add(row.location, {"kind": row.kind, **row.qualifiers})
    return list(found.values())


def _request_case(request: Request, outcome: dict[str, JsonValue]) -> JsonValue:
    level, location, qualifiers = request
    return {
        "level": level,
        "location": location,
        "qualifiers": cast(dict[str, JsonValue], qualifiers),
        "outcome": outcome,
    }


def _records(frame: pl.DataFrame) -> list[JsonValue]:
    return cast(list[JsonValue], frame.to_dicts())


def _absent_level(present: Iterator[str] | list[str]) -> str:
    held = set(present)
    return next(level for level in LEVELS if level not in held)


def catalog_cases(sets: Mapping[str, SourceCatalogues]) -> list[JsonValue]:
    """``Catalog`` answers for every set, software and version pattern of the packaged rules."""
    versions: dict[tuple[str, str], str] = {}
    for found in rules.rule_levels():
        pattern = found.software_version_pattern
        if pattern not in SAMPLE_VERSIONS:
            raise KeyError(f"no sample version for {pattern!r}; add one to SAMPLE_VERSIONS")
        sample = SAMPLE_VERSIONS[pattern]
        if re.search(pattern, sample) is None:
            raise ValueError(f"sample version {sample!r} does not match {pattern!r}")
        versions[(found.software_name, pattern)] = sample
    cases: list[JsonValue] = []
    for name, sources in sets.items():
        for (software, _), version in versions.items():
            catalog = Catalog(software, version, name)
            levels = [found.level for found in rules.matching(software, version)]
            asked = [
                request for level in dict.fromkeys(levels) for request in requests(sources, level)
            ]
            absent = _absent_level(levels)
            asked.append(
                (
                    absent,
                    "layers",
                    {"kind": next(iter(sources.vocabulary.qualifiers["kind"].values))},
                )
            )
            cases.append(
                {
                    "catalogue": name,
                    "software": software,
                    "version": version,
                    "requests": [
                        _request_case(request, _outcome(_catalog_answer(catalog, request)))
                        for request in asked
                    ],
                    "kinds": _kinds_cases(catalog, [*dict.fromkeys(levels), absent]),
                    "fields": _records(catalog.fields()),
                }
            )
    cases.append(
        {
            "catalogue": "abundance",
            "software": "DIA-NN",
            "version": "99.0",
            "error": "ValueError",
        }
    )
    return cases


def _catalog_answer(catalog: Catalog, request: Request) -> Callable[[], Reference | None]:
    level, location, qualifiers = request
    kind = qualifiers["kind"]
    others = {name: value for name, value in qualifiers.items() if name != "kind"}
    if location == "layers":
        return lambda: catalog.layer(level, kind, **others)
    if location == "obs":
        return lambda: catalog.obs(level, kind, **others)
    return lambda: catalog.var(level, kind, **others)


def _kinds_cases(catalog: Catalog | DataCatalog, levels: list[str]) -> list[JsonValue]:
    locations: tuple[Location, ...] = ("obs", "layers", "var")
    return [
        {
            "level": level,
            "location": location,
            "outcome": _kinds(
                lambda level=level, location=location: catalog.kinds(level, location)
            ),
        }
        for level in levels
        for location in locations
    ]


def data_catalog_cases(
    sets: Mapping[str, SourceCatalogues], results: Mapping[str, ParsedLevels]
) -> list[JsonValue]:
    """``DataCatalog`` answers for every synthetic result and set, with and without ``enforce``."""
    cases: list[JsonValue] = []
    for result, parsed in results.items():
        levels = list(parsed.levels)
        absent = _absent_level(levels)
        for name, sources in sets.items():
            enforced: tuple[Enforce, ...] = (
                (None, "MUST", "SHOULD") if sources.requirements else (None,)
            )
            for enforce in enforced:
                catalog = DataCatalog(parsed, name, enforce)
                asked: list[Request]
                if enforce is None:
                    asked = [request for level in levels for request in requests(sources, level)]
                else:
                    asked = [
                        (row.level, row.location, {"kind": row.kind, **row.qualifiers})
                        for row in sources.requirements
                        if row.level in parsed.levels
                    ]
                kind = next(iter(sources.vocabulary.qualifiers["kind"].values))
                asked.append((absent, "layers", {"kind": kind}))
                case: dict[str, JsonValue] = {
                    "result": result,
                    "catalogue": name,
                    "enforce": enforce,
                    "requests": [
                        _request_case(request, _outcome(_data_answer(catalog, request)))
                        for request in asked
                    ],
                }
                if enforce is None:
                    case["kinds"] = _kinds_cases(catalog, [*levels, absent])
                    case["fields"] = _records(catalog.fields())
                cases.append(case)
    cases.append(
        {
            "result": "edge-two-levels",
            "catalogue": "confidence",
            "enforce": "MUST",
            "error": "ValueError",
        }
    )
    return cases


def _data_answer(catalog: DataCatalog, request: Request) -> Callable[[], Reference | None]:
    level, location, qualifiers = request
    kind = qualifiers["kind"]
    others = {name: value for name, value in qualifiers.items() if name != "kind"}

    def answer() -> Reference | None:
        found = catalog._find(level, location, kind, others)  # pyright: ignore[reportPrivateUsage]
        return None if found is None else Reference.of(found)

    return answer


def table_cases(sets: Mapping[str, SourceCatalogues]) -> dict[str, JsonValue]:
    """The overview, rule coverage and long table of the packaged sets."""
    overview = pl.DataFrame(
        [
            {
                "catalogue": name,
                "purpose": sources.description.purpose,
                "used_by": list(sources.description.used_by),
                "has_requirements": bool(sources.requirements),
                "entries": sum(len(source.entries) for source in sources.sources()),
            }
            for name, sources in sets.items()
        ],
        schema=CATALOGUES_SCHEMA,
    )
    tables = {
        name: pl.DataFrame(set_rows(name, sources), schema=schema(sources))
        for name, sources in sets.items()
    }
    combined = pl.concat(list(tables.values()), how="diagonal")
    qualifiers = [column for column in combined.columns if column.startswith("qualifier.")]
    return {
        "catalogues": _records(overview),
        "rule_coverage": {name: _records(coverage_of(sources)) for name, sources in sets.items()},
        "catalogue_table": {
            "all": _records(combined.select(*KEY_COLUMNS, *qualifiers, "requirement", "entry_id")),
            **{name: _records(table) for name, table in tables.items()},
        },
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv))
