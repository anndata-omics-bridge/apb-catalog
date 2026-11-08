"""An installed package adds a catalogue set that answers like a packaged one."""

from __future__ import annotations

import logging
import re
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
        "abundance_alpha",
        "confidence_alpha",
        "proteobench_entrapment_alpha",
        "apb_alpha",
        "obs_annotation_alpha",
        "apb_fasta_alpha",
        "chromatography_alpha",
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
        lambda: {"confidence_alpha": TESTS / "toy_set"},
    )
    with pytest.raises(ValueError, match="names of packaged sets"):
        catalogue_descriptions()


def test_an_entry_point_names_the_package_holding_the_set() -> None:
    """The entry point's value is an importable package; its folder holds the set."""
    folders = plugin_folders(EntryPoints([EntryPoint("toy", "tests", PLUGIN_GROUP)]))
    assert folders["toy"].joinpath("toy_set", "catalog.csv").is_file()


def test_two_plugins_cannot_name_one_set() -> None:
    """Which one would answer is not guessed."""
    point = EntryPoint("toy", "tests", PLUGIN_GROUP)
    with pytest.raises(ValueError, match=r"several installed plugins .*\['toy'\]"):
        plugin_folders(EntryPoints([point, point]))


def _toy_folder(folder: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> Path:
    """The toy set copied under another name and installed as the only plugin.

    A set loaded without error stays cached by name, so each test that loads one names its own.
    """
    folder.mkdir()
    for found in (TESTS / "toy_set").glob("*.csv"):
        text = found.read_text("utf-8").replace("\ntoy,", f"\n{name},")
        (folder / found.name).write_text(text, "utf-8")
    monkeypatch.setattr("apb_catalog.source._plugin_folders", lambda: {name: folder})
    return folder


def _toy_copy(
    folder: Path, monkeypatch: pytest.MonkeyPatch, name: str, table: str, row: str
) -> str:
    """The toy set copied under another name, with one more row in one table."""
    target = _toy_folder(folder, monkeypatch, name) / f"{table}.csv"
    target.write_text(f"{target.read_text('utf-8')}{name},{row}\n", "utf-8")
    return name


def _replace(folder: Path, old: str, new: str, table: str = "catalog") -> None:
    """Rewrite one row of one table of the copied toy set."""
    path = folder / f"{table}.csv"
    text = path.read_text("utf-8")
    assert text.count(old) == 1
    path.write_text(text.replace(old, new), "utf-8")


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


GROUP = "DIA-NN/*,peptidoform_ion/var,-/Protein_Group,group,group,origin,vendor"
CHARGES = (
    "DIA-NN/*,peptidoform_ion/var,-/Precursor_Charge,charge,charge,origin",
    "FragPipe/*,peptidoform_ion/var,-/Charge,charge,charge,origin",
)


def test_a_plugin_key_fixes_a_qualifier_of_its_own_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A key can fix any qualifier its set declares, here the toy set's ``origin``: its term
    states the value, and its rows mark it fixed."""
    folder = _toy_folder(tmp_path / "toy_set", monkeypatch, "fixed_origin")
    _replace(folder, ",group,group,,,required,", ",group,group,origin,vendor,required,", "terms")
    _replace(folder, f"{GROUP},false,", f"{GROUP},true,")
    assert catalogue_set("fixed_origin").key("group").fixed == {"origin": "vendor"}


def test_a_row_carries_the_value_its_key_fixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The charge term fixes origin vendor; a charge row of apb2 marked fixed is refused."""
    folder = _toy_folder(tmp_path / "toy_set", monkeypatch, "fixed_two")
    _replace(
        folder, ",charge,charge,,,required,", ",charge,charge,origin,vendor,required,", "terms"
    )
    _replace(folder, f"{CHARGES[0]},vendor,false,", f"{CHARGES[0]},vendor,true,")
    _replace(folder, f"{CHARGES[1]},vendor,false,", f"{CHARGES[1]},apb2,true,")
    with pytest.raises(ValueError, match=r"\{'origin': 'apb2'\}; its key 'charge' fixes"):
        catalogue_set("fixed_two")


def test_a_term_exists_before_any_row_maps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A term no software maps yet loads with a warning, and its requirement still counts."""
    term = "peptidoform_ion/obs,group,group,,,recommended,,The sample group."
    name = _toy_copy(tmp_path / "toy_set", monkeypatch, "unmapped", "terms", term)
    with caplog.at_level(logging.WARNING, logger="apb_catalog.source"):
        found = catalogue_set(name)
    assert "('group', 'peptidoform_ion/obs')" in caplog.text
    requirement = found.requirement_for("peptidoform_ion", "obs", "group")
    assert requirement is not None
    assert requirement.requirement == "recommended"


def _second_qualifier(folder: Path, name: str, basis: str = "Synthetic test entry.") -> None:
    """Give the copied toy set the qualifier ``stage``, and every field a second row of it;
    the first field's second row carries ``basis``."""
    (folder / "qualifiers.csv").write_text(
        f"{(folder / 'qualifiers.csv').read_text('utf-8')}{name},stage,When.\n", "utf-8"
    )
    (folder / "qualifier_values.csv").write_text(
        f"{(folder / 'qualifier_values.csv').read_text('utf-8')}"
        f"{name},stage,raw,Raw.\n{name},stage,unknown,Not established.\n",
        "utf-8",
    )
    header, *rows = (folder / "catalog.csv").read_text("utf-8").splitlines()
    second = [re.sub(",origin,[^,]+,", ",stage,raw,", row) for row in rows]
    second[0] = second[0].replace(",Synthetic test entry.,", f",{basis},")
    lines = [line for pair in zip(rows, second, strict=True) for line in pair]
    (folder / "catalog.csv").write_text("\n".join([header, *lines, ""]), "utf-8")


def test_a_field_has_one_row_per_qualifier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every field of a set with two qualifiers has two rows, one each; they make one entry."""
    folder = _toy_folder(tmp_path / "toy_set", monkeypatch, "two_rows")
    _second_qualifier(folder, "two_rows")
    found = catalogue_set("two_rows")
    entries = [entry for source in found.sources() for entry in source.entries]
    assert len(entries) == len((folder / "catalog.csv").read_text("utf-8").splitlines()[1:]) // 2
    assert {tuple(entry.qualifiers) for entry in entries} == {("origin", "stage")}


def test_the_rows_of_a_field_share_its_basis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A field whose second row gives another basis is refused."""
    folder = _toy_folder(tmp_path / "toy_set", monkeypatch, "two_bases")
    _second_qualifier(folder, "two_bases", basis="Another basis.")
    with pytest.raises(ValueError, match="two bases or evidence URLs"):
        catalogue_set("two_bases")


EXTRA = "DIA-NN/*,peptidoform_ion/var,-/Extra"


@pytest.mark.parametrize(
    ("table", "row", "message"),
    [
        ("catalog", f"{EXTRA},group,group,origin,,false,,Synthetic.,", "a qualifier and a value"),
        (
            "catalog",
            f"{EXTRA},group,group,origin,elsewhere,false,,Synthetic.,",
            "not admit 'elsewhere'",
        ),
        ("catalog", f"{EXTRA},group,group,kind,charge,false,,Synthetic.,", "qualifies the kind"),
        (
            "catalog",
            f"{EXTRA},group,charge,origin,vendor,false,,Synthetic.,",
            "its key 'group' has 'group'",
        ),
        (
            "catalog",
            f"{EXTRA},group,group,origin,vendor,true,,Synthetic.,",
            r"fixed 'true' for \{'origin': 'vendor'\}; its key 'group' fixes \{\}",
        ),
        ("catalog", f"{EXTRA},group,group,origin,vendor,TRUE,,Synthetic.,", "fixed 'TRUE'"),
        (
            "catalog",
            "DIA-NN/*,peptidoform_ion/obs,-/Extra,group,group,origin,vendor,false,,Synthetic.,",
            "terms.csv does not define",
        ),
        ("catalog", f"{GROUP},false,,Synthetic test entry.,", "catalog.csv repeats the keys"),
        ("terms", "peptidoform_ion/obs,charm,charm,,,,,", "admit the kind 'charm'"),
        ("terms", "peptidoform_ion/obs,group,charge,,,,,", "'group' has the kinds"),
        ("terms", "peptidoform_ion/obs,group,group,origin,vendor,,,", "at different locations"),
        ("terms", "peptidoform_ion/obs,group,group,origin,,,,", "a pair names a qualifier"),
        ("terms", "peptidoform_ion/var,group,group,origin,vendor,,,", "a row without a pair"),
        ("terms", "peptidoform_ion/obs,charge,charge,,,always,,", "Input should be 'required'"),
        ("terms", "peptidoform_ion/var,group,group,,,,,", "terms.csv repeats the keys"),
        ("qualifiers", "kind,Which synthetic field.", "qualifiers.csv declares 'kind'"),
        ("qualifier_values", "flavour,sweet,A taste.", "defines 'sweet' of no qualifier"),
        ("sets", "again,Again.,Again.,Again.,tests", r"sets.csv repeats the keys"),
    ],
)
def test_a_plugin_folder_holds_one_set_its_kinds_and_its_qualifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, table: str, row: str, message: str
) -> None:
    """In ``catalog.csv``: half a qualifier pair, an unadmitted value, a qualified kind, a kind
    other than its key's, a fixed value its key does not fix, a ``fixed`` other than true or
    false, a term ``terms.csv`` does not define there, a field with two rows of one qualifier.
    In ``terms.csv``: an unadmitted kind, a key with two kinds or fixing different values at two
    locations, half a pair, a pair beside a row without one, an unknown requirement, a repeated
    term. A qualifier named ``kind``; a value of no qualifier; a second row for the set: all
    refused."""
    name = _toy_copy(tmp_path / "toy_set", monkeypatch, "broken", table, row)
    with pytest.raises(ValueError, match=message):
        catalogue_set(name)


def test_a_set_declared_alone_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A set with only its ``sets.csv`` row, no kinds, terms or entries, is being planned: it
    loads, with no key and nothing to answer."""
    folder = tmp_path / "planned"
    folder.mkdir()
    (folder / "sets.csv").write_text(
        "set,prefix,definition,kind_definition,purpose,used_by\nplanned,pl,,,,\n", "utf-8"
    )
    monkeypatch.setattr("apb_catalog.source._plugin_folders", lambda: {"planned": folder})
    found = catalogue_set("planned")
    assert (found.keys, found.sources(), found.requirements) == ((), (), ())
