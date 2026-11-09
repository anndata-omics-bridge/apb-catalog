"""Every Python example in ``docs/`` runs, and what it shows is what it returns.

Each page runs in a fresh folder holding the synthetic ``diann.h5mu`` and ``diann.parquet`` of
``tests/doc_results.py``; its blocks run in order and share their names, as a reader runs
them. Two checks tie the page to the code:

- A comment that is a Python literal, after an expression, is that expression's value:
  ``ion.layers.keys()  # {'pep', 'q_value'}``. A comment that is prose is not checked.
- A ``text`` block right after a block is what the block prints or, when it prints nothing,
  the ``repr`` of its last expression.

A block that cannot run here, such as one using a plugin set that is not installed, is preceded
by ``<!-- not run: <reason> -->``.
"""

from __future__ import annotations

import ast
import contextlib
import io
import re
import shutil
import tokenize
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.doc_results import write_results

DOCS = Path(__file__).parents[1] / "docs"
BLOCK = re.compile(
    r"(?P<skip><!-- not run: [^>]+-->\n)?```python\n(?P<code>.*?)```\n"
    r"(?:\n*```text\n(?P<shown>.*?)```\n)?",
    re.DOTALL,
)
# Pages that also run on another variant of the result; every page runs on "plain".
VARIANTS = {"exporters.md": ("plain", "fasta")}


@dataclass(frozen=True, slots=True)
class Example:
    """One ``python`` block of a page and the output shown after it."""

    line: int
    code: str
    shown: str | None


def _examples(page: Path) -> list[Example]:
    text = page.read_text("utf-8")
    return [
        Example(text.count("\n", 0, match.start("code")) + 1, match["code"], match["shown"])
        for match in BLOCK.finditer(text)
        if match["skip"] is None
    ]


def _cases() -> list[tuple[str, str]]:
    pages = sorted(page.name for page in DOCS.glob("*.md") if _examples(page))
    return [(page, variant) for page in pages for variant in VARIANTS.get(page, ("plain",))]


def _literal_comments(code: str) -> dict[int, object]:
    """Each line's trailing comment that is a Python literal, by line."""
    found: dict[int, object] = {}
    for token in tokenize.generate_tokens(io.StringIO(code).readline):
        if token.type != tokenize.COMMENT:
            continue
        with contextlib.suppress(ValueError, SyntaxError):
            found[token.start[0]] = ast.literal_eval(token.string.removeprefix("#").strip())
    return found


def _run(example: Example, where: str, namespace: dict[str, object]) -> None:
    expected = _literal_comments(example.code)
    printed = io.StringIO()
    last: object = None
    with contextlib.redirect_stdout(printed):
        for statement in ast.parse(example.code).body:
            line = example.line + statement.lineno - 1
            if isinstance(statement, ast.Expr):
                last = eval(compile(ast.Expression(statement.value), where, "eval"), namespace)
                if statement.end_lineno in expected:
                    shown = expected[statement.end_lineno]
                    assert last == shown, f"{where}:{line}: returns {last!r}, the page {shown!r}"
            else:
                exec(compile(ast.Module([statement], []), where, "exec"), namespace)
                last = None
    if example.shown is not None:
        output = printed.getvalue() or repr(last)
        assert output.strip() == example.shown.strip(), f"{where}:{example.line}: output differs"


@pytest.fixture(scope="session")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return write_results(tmp_path_factory.mktemp("doc_results"))


@pytest.mark.parametrize(("page", "variant"), _cases())
def test_the_page_runs_as_written(
    page: str,
    variant: str,
    results: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shutil.copytree(results[variant], tmp_path, dirs_exist_ok=True)
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, object] = {"__name__": "__docs__"}
    for example in _examples(DOCS / page):
        _run(example, f"docs/{page}", namespace)
