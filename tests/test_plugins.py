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
    assert (toy["has_requirements"], toy["entries"]) == (True, 22)


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
    """Its qualifiers are its own, under the packaged vocabulary version."""
    sources = catalogue_set(toy_set)
    assert set(sources.vocabulary.qualifiers) == {"kind", "origin"}
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


def _toy_copy(folder: Path, monkeypatch: pytest.MonkeyPatch, name: str, key_qualifier: str) -> str:
    """The toy set copied under another name, with one ``key_qualifiers.csv`` row.

    A set loaded without error stays cached by name, so each test that loads one names its own.
    """
    folder.mkdir()
    for table in (TESTS / "toy_set").glob("*.csv"):
        text = table.read_text("utf-8").replace("\ntoy,", f"\n{name},")
        (folder / table.name).write_text(text, "utf-8")
    (folder / "key_qualifiers.csv").write_text(
        f"set,key,qualifier,value\n{name},{key_qualifier}\n", "utf-8"
    )
    monkeypatch.setattr("apb_catalog.source._plugin_folders", lambda: {name: folder})
    return name


def test_a_plugin_key_fixes_a_qualifier_of_its_own_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key can fix any qualifier its set declares, here the toy set's ``origin``."""
    name = _toy_copy(tmp_path / "toy_set", monkeypatch, "fixed_origin", "group,origin,vendor")
    assert catalogue_set(name).key("group").fixed == {"origin": "vendor"}


@pytest.mark.parametrize(
    ("key_qualifier", "message"),
    [
        ("no_such_key,origin,vendor", r"qualifies no key \['no_such_key'\]"),
        ("group,origin,elsewhere", "does not admit 'elsewhere'"),
        ("group,kind,charge", "fixes the kind of 'group'"),
    ],
)
def test_a_key_qualifier_names_a_key_and_a_value_of_the_vocabulary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key_qualifier: str, message: str
) -> None:
    """A row naming no key, a value the vocabulary does not admit, or the kind is refused."""
    name = _toy_copy(tmp_path / "toy_set", monkeypatch, "broken", key_qualifier)
    with pytest.raises(ValueError, match=message):
        catalogue_set(name)
