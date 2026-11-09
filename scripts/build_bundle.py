"""Build the bundles other languages implement apb-catalog on: the bundle and its test bundle.

``make bundle`` writes ``build/apb-catalog-bundle/`` and ``build/apb-catalog-test-bundle/``, each
with its ``.tar.gz``. The release workflow attaches both archives to the GitHub release and copies
both folders into apbCatalogR.

The bundle is what a reader looks fields up with: the packaged catalogue tables, CSV files
described by their ``datapackage.json``, ``versions.csv`` among them. The test bundle holds
synthetic Parquet results built from APB2's effective rule declarations (packed in
``results.tar.gz``) and the answers this package gives on them.
Only packaged sets enter; an installed plugin set never does.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import replace
from importlib import metadata, resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import cast, override

import polars as pl
from apb2.api import (
    JsonValue,
    ParsedLevel,
    ParsedLevels,
    packaged_rule_declarations,
    write_parsed_levels,
)

from apb_catalog import rules
from apb_catalog.catalog import (
    Catalog,
    DataCatalog,
    Enforce,
    MissingRequiredField,
)
from apb_catalog.coverage import CATALOGUES_SCHEMA, coverage_of
from apb_catalog.levels import Level, LevelNames, Slot
from apb_catalog.resolver import UnresolvedField
from apb_catalog.rules import ANY, Location
from apb_catalog.source import (
    TABLES,
    SourceCatalogues,
    packaged_catalogues,
    packaged_descriptions,
)
from apb_catalog.table import KEY_COLUMNS, schema, set_rows

NAME = "apb-catalog-bundle"
TEST_NAME = "apb-catalog-test-bundle"
BUNDLE_FORMAT = 4
"""Raised when a reader of the previous format could not read the bundle."""


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
type Request = tuple[str, Location, str, dict[str, str]]


def main(argv: list[str]) -> int:
    """Build both bundle folders and their archives under ``argv[1]``, ``build`` by default."""
    target = Path(argv[1]) if len(argv) > 1 else Path("build")
    for folder in build(target):
        archive = target / f"{folder.name}.tar.gz"
        with tarfile.open(archive, "w:gz") as packed:
            packed.add(folder, arcname=folder.name)
        print(f"wrote {folder} and {archive}")
    return 0


def build(target: Path) -> tuple[Path, Path]:
    """Write the bundle and the test bundle into ``target``, replacing what is there."""
    names = list(packaged_descriptions())
    bundle = _fresh(target / NAME)
    _write_catalogues(bundle / "catalogues", names)
    _write_manifest(bundle, names)
    tests = _fresh(target / TEST_NAME)
    results = synthetic_results()
    _write_results(tests / "results.tar.gz", results)
    sets = {name: packaged_catalogues(name) for name in names}
    _write_json(tests / "cases" / "catalog.json", catalog_cases(sets))
    _write_json(tests / "cases" / "data_catalog.json", data_catalog_cases(sets, results))
    _write_json(tests / "cases" / "tables.json", table_cases(sets))
    _write_manifest(tests, names)
    return bundle, tests


def _fresh(folder: Path) -> Path:
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    return folder


def _write_manifest(folder: Path, names: list[str]) -> None:
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


def _write_catalogues(folder: Path, names: list[str]) -> None:
    """The packaged catalogue tables and their ``datapackage.json``, after loading each set
    checks them."""
    for name in names:
        packaged_catalogues(name)
    data = resources.files("apb_catalog").joinpath("data")
    for name in ("datapackage.json", "versions.csv", *(f"{table}.csv" for table in TABLES)):
        _copy(data.joinpath(name), folder / name)


def _copy(source: Traversable, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source.read_text("utf-8"), "utf-8")


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
    obs_extra: Mapping[str, list[str]] | None = None,
    stored: bool = True,
) -> ParsedLevel:
    """Two samples and three features with every field the rule level's first declaration keeps.

    ``stored=False`` leaves out ``rule_json``.
    """
    declared = _declaration(rule, level)
    axis = cast(dict[str, list[str]], declared["axis"])
    columns = cast(dict[str, list[dict[str, JsonValue]]], declared["columns"])
    obs: dict[str, list[object]] = {
        key: [f"S{i}" for i in range(SAMPLES)] for key in axis["obs_keys"]
    }
    # A computed entry has no type in the stored rule: its value is text.
    for column in columns.get("obs", []):
        obs.setdefault(str(column["name"]), _values(str(column.get("type", "string")), SAMPLES))
    obs |= {name: list(values) for name, values in (obs_extra or {}).items()}
    var: dict[str, list[object]] = {
        key: [f"F{i}" for i in range(FEATURES)] for key in axis["var_keys"]
    }
    for column in columns.get("var", []):
        var.setdefault(str(column["name"]), _values(str(column.get("type", "string")), FEATURES))
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
        uns["provenance"] = {"rule_json": packaged_rule_declarations()[(rule, level)][0]}
    return ParsedLevel.build(
        pl.DataFrame(obs),
        axis["obs_keys"],
        pl.DataFrame(var),
        axis["var_keys"],
        _roles(declared),
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


def _declaration(rule: str, level: str) -> Declaration:
    """The first effective declaration of a packaged rule level."""
    return cast(Declaration, json.loads(packaged_rule_declarations()[(rule, level)][0]))


def _roles(declared: Declaration) -> dict[str, str]:
    """The var column each role names in one declaration."""
    columns = cast(dict[str, list[dict[str, JsonValue]]], declared["columns"])
    return {
        role: str(column["name"])
        for column in columns.get("var", [])
        for role in cast(list[str], column.get("roles") or [])
    }


MAXQUANT = "maxquant_wide/rules.json"
DIANN = "diann/v2/rules.json"


def _edge_results() -> dict[str, ParsedLevels]:
    """Results that exercise an unreviewed level, both annotation conventions and apb-fasta's
    peptide verification and protein annotation."""
    ion = "peptidoform_ion"
    two_levels = {level: synthetic_level(DIANN, level) for level in (ion, "protein")}
    verified = replace(
        synthetic_level(DIANN, ion),
        varm={
            "fasta_validation": pl.DataFrame(
                {
                    "peptide_in_fasta": [True, True, False],
                    "fasta_matches_contaminant": [False, True, False],
                    "fasta_matching_organisms": ["HUMAN", "HUMAN;BOVIN", ""],
                }
            )
        },
    )
    annotated = replace(
        synthetic_level(DIANN, "protein"),
        varm={
            "fasta": pl.DataFrame(
                {
                    "any_member_in_fasta": [True, True, False],
                    "fasta_gene_names": ["ALB", "KRT1;KRT2", ""],
                    "fasta_descriptions": ["Albumin", "Keratin 1;Keratin 2", ""],
                    "fasta_organism_names": ["Homo sapiens", "Homo sapiens", ""],
                }
            )
        },
    )
    return {
        "edge-fasta": _one(ion, verified, {"fasta": {"provenance": {"peptide_verification": {}}}}),
        "edge-fasta-proteins": _one(
            "protein", annotated, {"fasta": {"provenance": {"protein_annotation": {}}}}
        ),
        "edge-unreviewed": _one(ion, synthetic_level(MAXQUANT, ion, stored=False)),
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
    """Collects the warning a catalog logs when it opens, for missing fields it does not raise
    for."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _outcome(answer: Callable[[], str | None]) -> dict[str, JsonValue]:
    """What one lookup gives: the field's name, ``null``, or the ``UnresolvedField`` it raises."""
    try:
        found = answer()
    except UnresolvedField as error:
        return {"error": "UnresolvedField", "status": error.resolution.status}
    return {"name": found}


def _opened(
    parsed: ParsedLevels, name: str, enforce: Enforce
) -> tuple[DataCatalog | None, dict[str, JsonValue]]:
    """The catalog, or what opening it raises: the error's class with every missing field or its
    message; and whether it logged a ``MissingRequiredField`` warning."""
    handler = _Warnings()
    logger = logging.getLogger("apb_catalog")
    logger.addHandler(handler)
    opened: dict[str, JsonValue] = {}
    catalog: DataCatalog | None = None
    try:
        catalog = DataCatalog(parsed, name, enforce=enforce)
    except MissingRequiredField as error:
        opened["error"] = type(error).__name__
        opened["missing"] = [
            [row.level, row.location, row.key, row.requirement] for _, row in error.missing
        ]
    except ValueError as error:
        opened |= {"error": type(error).__name__, "message": str(error)}
    finally:
        logger.removeHandler(handler)
    if handler.records:
        opened["warning"] = "MissingRequiredField"
    return catalog, opened


def _keys(answer: Callable[[], tuple[str, ...]]) -> dict[str, JsonValue]:
    try:
        return {"keys": list(answer())}
    except UnresolvedField as error:
        return {"error": "UnresolvedField", "status": error.resolution.status}


def requests(sources: SourceCatalogues, level: str) -> list[Request]:
    """Every request a set's entries and requirement rows on one level ask, without repeats.

    Each entry asks for its key once with the qualifiers its key leaves open and once alone; each
    request is asked again with the set's prefix, as ``c:q_value``.
    """
    found: dict[str, Request] = {}

    def add(location: Location, key: str, qualifiers: dict[str, str]) -> None:
        seen = json.dumps([location, key, qualifiers], sort_keys=True)
        found.setdefault(seen, (level, location, key, qualifiers))

    for source in sources.sources():
        for entry in source.entries:
            if entry.reference.level not in (level, ANY):
                continue
            location: Location = (
                "var" if entry.reference.location == "varm" else entry.reference.location
            )
            fixed = sources.key(entry.key).fixed
            add(
                location,
                entry.key,
                {name: value for name, value in entry.qualifiers.items() if name not in fixed},
            )
            add(location, entry.key, {})
    for row in sources.requirements:
        if row.level == level:
            add(row.location, row.key, {})
    plain = list(found.values())
    prefix = sources.vocabulary.prefix
    return [
        *plain,
        *((at, location, f"{prefix}:{key}", qualifiers) for at, location, key, qualifiers in plain),
    ]


def vendor_requests(sources: SourceCatalogues, level: str) -> list[Request]:
    """A ``v:`` request for the own name of every entry on one level outside ``varm``."""
    found: dict[tuple[Location, str], Request] = {}
    for source in sources.sources():
        for entry in source.entries:
            reference = entry.reference
            if reference.level not in (level, ANY) or reference.location == "varm":
                continue
            if reference.name is None:
                continue
            location: Location = reference.location
            found.setdefault(
                (location, reference.name), (level, location, f"v:{reference.name}", {})
            )
    return list(found.values())


def _request_case(request: Request, outcome: dict[str, JsonValue]) -> JsonValue:
    level, location, key, qualifiers = request
    return {
        "level": level,
        "location": location,
        "key": key,
        "qualifiers": cast(dict[str, JsonValue], qualifiers),
        "outcome": outcome,
    }


def _records(frame: pl.DataFrame) -> list[JsonValue]:
    return cast(list[JsonValue], frame.to_dicts())


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
            cases.append(
                {
                    "catalogue": name,
                    "software": software,
                    "version": version,
                    "requests": [
                        _request_case(request, _outcome(_named(catalog.levels, request)))
                        for request in asked
                    ],
                    "keys": _keys_cases(catalog.levels),
                    "fields": _records(catalog.fields()),
                }
            )
    cases.append(
        {
            "catalogue": "abundance_alpha",
            "software": "DIA-NN",
            "version": "99.0",
            "error": "ValueError",
        }
    )
    return cases


def _slot(level: Level | LevelNames, location: Location) -> Slot[object]:
    if location == "layers":
        return level.layers
    return level.obs if location == "obs" else level.var


def _named(levels: Mapping[str, Level | LevelNames], request: Request) -> Callable[[], str | None]:
    """The name of the field one request reads through a level's slot, ``None`` for none."""
    level, location, key, qualifiers = request

    def answer() -> str | None:
        try:
            return _slot(levels[level], location).name(key, **qualifiers)
        except KeyError:
            return None

    return answer


def _keys_cases(levels: Mapping[str, Level | LevelNames]) -> list[JsonValue]:
    locations: tuple[Location, ...] = ("obs", "layers", "var")
    return [
        {
            "level": name,
            "location": location,
            "outcome": _keys(
                lambda level=level, location=location: tuple(sorted(_slot(level, location).keys()))
            ),
        }
        for name, level in levels.items()
        for location in locations
    ]


def data_catalog_cases(
    sets: Mapping[str, SourceCatalogues], results: Mapping[str, ParsedLevels]
) -> list[JsonValue]:
    """``DataCatalog`` answers for every synthetic result and set, with and without ``enforce``;
    a catalog that cannot open records what it raises instead."""
    cases: list[JsonValue] = []
    for result, parsed in results.items():
        levels = list(parsed.levels)
        for name, sources in sets.items():
            enforced: tuple[Enforce, ...] = (
                (None, "required", "recommended") if sources.requirements else (None,)
            )
            for enforce in enforced:
                catalog, opened = _opened(parsed, name, enforce)
                if catalog is None:
                    cases.append({"result": result, "catalogue": name, "enforce": enforce} | opened)
                    continue
                asked: list[Request]
                if enforce is None:
                    asked = [
                        request
                        for level in levels
                        for request in (*requests(sources, level), *vendor_requests(sources, level))
                    ]
                else:
                    asked = [
                        (row.level, row.location, row.key, {})
                        for row in sources.requirements
                        if row.level in parsed.levels
                    ]
                case: dict[str, JsonValue] = {
                    "result": result,
                    "catalogue": name,
                    "enforce": enforce,
                    "requests": [
                        _request_case(request, _outcome(_named(catalog.levels, request)))
                        for request in asked
                    ],
                }
                case |= opened
                if enforce is None:
                    case["keys"] = _keys_cases(catalog.levels)
                    case["fields"] = _records(catalog.fields())
                cases.append(case)
    return cases


def table_cases(sets: Mapping[str, SourceCatalogues]) -> dict[str, JsonValue]:
    """The overview, rule coverage and long table of the packaged sets."""
    overview = pl.DataFrame(
        [
            {
                "catalogue": name,
                "prefix": sources.vocabulary.prefix,
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
            "all": _records(
                combined.select(*KEY_COLUMNS, "key", "kind", *qualifiers, "requirement", "entry_id")
            ),
            **{name: _records(table) for name, table in tables.items()},
        },
    }


if __name__ == "__main__":
    sys.exit(main(sys.argv))
