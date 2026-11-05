"""An installed package adds a catalogue set that answers like a packaged one."""

from __future__ import annotations

from importlib.metadata import EntryPoint, EntryPoints
from pathlib import Path

import polars as pl
import pytest

from apb_catalog.coverage import catalogues, rule_coverage
from apb_catalog.source import (
    PLUGIN_GROUP,
    catalog_version,
    catalogue_descriptions,
    catalogue_set,
    plugin_folders,
)
from tests.conftest import TESTS


def test_a_plugin_set_is_listed_with_the_packaged_ones(toy_set: str) -> None:
    """The overview counts its entries and reports its requirements."""
    listed = catalogues()
    assert listed.get_column("catalogue").to_list() == [
        "abundance",
        "confidence",
        "proteobench_entrapment",
        "apb",
        "chromatography",
        toy_set,
    ]
    toy = listed.filter(pl.col("catalogue") == toy_set).row(0, named=True)
    assert (toy["prefix"], toy["has_requirements"], toy["entries"]) == ("toy", True, 22)


def test_a_plugin_sets_requirements_judge_its_vendors_levels(toy_set: str) -> None:
    """DIA-NN supplies every required field; FragPipe names no protein group; a set with vendor
    entries reviews every packaged rule level, so a vendor it catalogues nothing of fails."""
    judged = (
        rule_coverage(toy_set)
        .filter(pl.col("verdict").is_not_null())
        .unique(["software", "software_version_pattern", "level"])
        .group_by("software")
        .agg(pl.col("verdict").unique().sort())
    )
    verdicts = dict(judged.iter_rows())
    assert (verdicts.pop("DIA-NN"), verdicts.pop("FragPipe")) == (["pass"], ["fail"])
    assert verdicts and all(found == ["fail"] for found in verdicts.values())


def test_a_plugin_set_brings_its_own_vocabulary(toy_set: str) -> None:
    """Its kinds and qualifiers are its own, under the packaged vocabulary version."""
    sources = catalogue_set(toy_set)
    assert set(sources.vocabulary.qualifiers) == {"origin"}
    assert set(sources.vocabulary.kinds) == {
        "group",
        "charge",
        "decoy",
        "contaminant",
        "peptidoform",
        "unknown",
    }
    assert sources.vocabulary_version == catalog_version()


def test_an_unknown_set_names_packaged_and_plugin_sets(toy_set: str) -> None:
    """Both kinds of set are offered."""
    with pytest.raises(ValueError, match=r"packaged: \[.*\], plugins: \['toy'\]"):
        catalogue_set("nope")


def test_a_plugin_cannot_take_a_packaged_sets_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged set keeps its name."""
    monkeypatch.setattr(
        "apb_catalog.source._plugin_folders",
        lambda: {"confidence": TESTS / "toy_set"},
    )
    with pytest.raises(ValueError, match="names of packaged sets"):
        catalogue_descriptions()


def test_an_entry_point_names_the_package_holding_the_set() -> None:
    """The entry point's value is an importable package; its folder holds the set."""
    folders = plugin_folders(EntryPoints([EntryPoint("toy", "tests", PLUGIN_GROUP)]))
    assert folders["toy"].joinpath("toy_set", "entries.csv").is_file()


def test_two_plugins_cannot_name_one_set() -> None:
    """Which one would answer is not guessed."""
    point = EntryPoint("toy", "tests", PLUGIN_GROUP)
    with pytest.raises(ValueError, match=r"several installed plugins .*\['toy'\]"):
        plugin_folders(EntryPoints([point, point]))


def _toy_copy(
    folder: Path, monkeypatch: pytest.MonkeyPatch, name: str, table: str, row: str
) -> str:
    """The toy set copied under another name, with one more row in one table.

    A set loaded without error stays cached by name, so each test that loads one names its own.
    """
    folder.mkdir()
    for found in (TESTS / "toy_set").glob("*.csv"):
        text = found.read_text("utf-8").replace("\ntoy,", f"\n{name},")
        (folder / found.name).write_text(text, "utf-8")
    target = folder / f"{table}.csv"
    header = target.read_text("utf-8") if target.is_file() else f"{_HEADERS[table]}\n"
    target.write_text(f"{header}{name},{row}\n", "utf-8")
    monkeypatch.setattr("apb_catalog.source._plugin_folders", lambda: {name: folder})
    return name


_HEADERS = {"key_qualifiers": "set,key,qualifier,value"}


@pytest.mark.parametrize(
    ("name", "prefix", "message"),
    [
        ("prefix_vendor", "v", "reserved for the vendor's own column"),
        ("prefix_upper", "C", "does not match"),
        ("prefix_packaged", "c", r"share the prefixes \['c'\]"),
    ],
)
def test_a_plugin_set_has_a_prefix_of_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, prefix: str, message: str
) -> None:
    """The vendor's ``v``, a prefix out of pattern and a packaged set's prefix: all refused."""
    folder = tmp_path / "toy_set"
    folder.mkdir()
    for found in (TESTS / "toy_set").glob("*.csv"):
        text = found.read_text("utf-8").replace("\ntoy,toy,", f"\n{name},{prefix},")
        (folder / found.name).write_text(text.replace("\ntoy,", f"\n{name},"), "utf-8")
    monkeypatch.setattr("apb_catalog.source._plugin_folders", lambda: {name: folder})
    with pytest.raises(ValueError, match=message):
        catalogue_set(name)


def test_a_plugin_key_fixes_a_qualifier_of_its_own_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key can fix any qualifier its set declares, here the toy set's ``origin``."""
    name = _toy_copy(
        tmp_path / "toy_set", monkeypatch, "fixed_origin", "key_qualifiers", "group,origin,vendor"
    )
    assert catalogue_set(name).key("group").fixed == {"origin": "vendor"}


@pytest.mark.parametrize(
    ("table", "row", "message"),
    [
        ("key_qualifiers", "no_such_key,origin,vendor", r"qualifies no key \['no_such_key'\]"),
        ("key_qualifiers", "group,origin,elsewhere", "does not admit 'elsewhere'"),
        ("key_qualifiers", "group,kind,charge", "fixes the kind of 'group'"),
        ("qualifiers", "kind,Which synthetic field.", "qualifiers.csv declares 'kind'"),
        ("qualifier_values", "flavour,sweet,A taste.", "defines 'sweet' of no qualifier"),
        ("sets", "again,Again.,Again.,Again.,tests", r"sets.csv repeats the keys"),
        ("keys", "charm,charm,", "key 'charm': the set does not admit the kind 'charm'"),
    ],
)
def test_a_plugin_folder_holds_one_set_its_kinds_and_its_qualifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str, row: str, message: str
) -> None:
    """A key qualifier naming no key, an unadmitted value or the kind; a qualifier named
    ``kind``; a value of no qualifier; a second row for the set; a key of no kind: all refused."""
    name = _toy_copy(tmp_path / "toy_set", monkeypatch, "broken", table, row)
    with pytest.raises(ValueError, match=message):
        catalogue_set(name)
