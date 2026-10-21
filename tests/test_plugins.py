"""An installed package adds a catalogue set that answers like a packaged one."""

from __future__ import annotations

from importlib.metadata import EntryPoint, EntryPoints

import polars as pl
import pytest

from apb_catalog.coverage import catalogues, rule_coverage
from apb_catalog.source import PLUGIN_GROUP, catalogue_descriptions, catalogue_set, plugin_folders
from apb_catalog.vocabulary import packaged_vocabulary
from tests.conftest import TESTS


def test_a_plugin_set_is_listed_with_the_packaged_ones(toy_set: str) -> None:
    """The overview counts its entries and reports its requirements."""
    listed = catalogues()
    assert listed.get_column("catalogue").to_list() == [
        "identification_confidence",
        "proteobench_entrapment",
        toy_set,
    ]
    toy = listed.filter(pl.col("catalogue") == toy_set).row(0, named=True)
    assert (toy["has_requirements"], toy["entries"]) == (True, 8)


def test_a_plugin_sets_requirements_judge_its_vendors_levels(toy_set: str) -> None:
    """DIA-NN supplies every MUST field; FragPipe names no protein group."""
    judged = (
        rule_coverage(toy_set)
        .filter(pl.col("verdict").is_not_null())
        .unique(["rule", "level"])
        .group_by("software")
        .agg(pl.col("verdict").unique().sort())
    )
    assert dict(judged.iter_rows()) == {"DIA-NN": ["pass"], "FragPipe": ["fail"]}


def test_the_plugin_vocabulary_joins_the_packaged_one(toy_set: str) -> None:
    """Its concepts sit beside the packaged ones, under the packaged version."""
    vocabulary = catalogue_set(toy_set).vocabulary
    packaged = packaged_vocabulary()
    assert set(vocabulary.concepts) == {*packaged.concepts, "toy"}
    assert vocabulary.vocabulary_version == packaged.vocabulary_version


def test_an_unknown_set_names_packaged_and_plugin_sets(toy_set: str) -> None:
    """Both kinds of set are offered."""
    with pytest.raises(ValueError, match=r"packaged: \[.*\], plugins: \['toy'\]"):
        catalogue_set("nope")


def test_a_plugin_cannot_take_a_packaged_sets_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged set keeps its name."""
    monkeypatch.setattr(
        "apb_catalog.source._plugin_folders",
        lambda: {"identification_confidence": TESTS / "toy_set"},
    )
    with pytest.raises(ValueError, match="names of packaged sets"):
        catalogue_descriptions()


def test_a_plugin_cannot_redefine_a_packaged_concept(monkeypatch: pytest.MonkeyPatch) -> None:
    """A packaged concept keeps its meaning."""
    monkeypatch.setattr(
        "apb_catalog.source._plugin_folders", lambda: {"clash": TESTS / "clash_set"}
    )
    with pytest.raises(ValueError, match=r"redefines packaged concepts \['confidence'\]"):
        catalogue_set("clash")


def test_an_entry_point_names_the_package_holding_the_set() -> None:
    """The entry point's value is an importable package; its folder holds the set."""
    folders = plugin_folders(EntryPoints([EntryPoint("toy", "tests", PLUGIN_GROUP)]))
    assert folders["toy"].joinpath("toy_set", "catalogue.json").is_file()


def test_two_plugins_cannot_name_one_set() -> None:
    """Which one would answer is not guessed."""
    point = EntryPoint("toy", "tests", PLUGIN_GROUP)
    with pytest.raises(ValueError, match=r"several installed plugins .*\['toy'\]"):
        plugin_folders(EntryPoints([point, point]))
