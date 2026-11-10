# APB Catalog — agent rules

The closest `AGENTS.md` wins. Explicit user instructions override this file.

## Verified commands

| Task | Command |
| --- | --- |
| Synchronize | `uv sync --group dev` |
| Format | `.venv/bin/ruff format src tests scripts && .venv/bin/ruff check --fix src tests scripts` |
| Lint | `.venv/bin/ruff check src tests scripts` |
| Typecheck | `.venv/bin/pyright` |
| Dependencies | `.venv/bin/deptry .` |
| Tests | `.venv/bin/pytest --cov --cov-branch` |
| Docs tables | `make docs-tables` |
| Build | `uv build && .venv/bin/twine check dist/*` |
| Full gate | `make check` |

## Code conventions

- Fully annotate every function and method in `src/` and `tests/`, including
  private functions, callbacks, generators, fixtures, and special methods.
- Standard Pyright strict and Ruff are mandatory. Do not create baselines,
  blanket exclusions, file-wide ignores, or unqualified `# type: ignore`.
- Ruff is the sole formatter and linter. Do not add Black, isort, Flake8, mypy,
  or another overlapping formatter/type checker.
- Keep `__init__.py` empty and import from defining modules inside this package. Other anndata_bridge packages import this one only from `apb_catalog.api`, or `apb_catalog.api_pandas` for the pandas API on AnnData objects, and it imports them only from theirs.
- Use Google-style docstrings for public APIs and the configured 100-character
  line length.

## Lookup behaviour

- The catalog is scverse AnnData plus a mapping layer, nothing new: a name is tried as a catalog key, then as the level's own field, and otherwise answers exactly as AnnData does. `get` returns `None` where `adata.var.get` and `adata.layers.get` do; `[...]` raises `KeyError` where AnnData raises it
- Add no errors, defaults or guards of the catalog's own for a name it cannot map; the API user handles `None`
- Before calling a lookup behaviour a problem, check what AnnData does; only a deviation from AnnData is one. The full contract is in [docs/api.md](docs/api.md)

## What the catalog holds

- A row exists because a downstream application reads it (apb-export, apb-aggregate, apb-proteobench, …). A new apb2 level, layer or column gets no row until an application reads it
- apb2 tests what it converts; apb-catalog tests what downstream applications need. No apb-catalog test requires the catalog to cover every level, layer or column apb2 writes
- When an apb2 change fails a catalog test, first ask which application reads the field. If none does, the test is the defect, not the catalog

## Dependency rules

### Required

- Declare every imported runtime dependency directly in `[project.dependencies]`.
- Put tests, linting, typing, building, and documentation tools in dependency
  groups; optional user-facing capabilities belong in extras.
- Update `pyproject.toml` and run `make check`; the repository commits no `uv.lock`.

### Recommended

- Prefer the standard library, then an existing direct dependency, then a small,
  maintained, typed dependency.
- Keep source independent of test, build, documentation, and CLI-only packages.

### Forbidden

- Depend on unpinned branches or undeclared transitive dependencies.
- Add parallel manifests, lockfiles, formatters, type checkers, or test runners.
- Silence a dependency or typing defect instead of fixing its source.

## Workflow

1. Preserve unrelated worktree changes.
2. Add or update focused tests with each behavioral change.
3. Run the smallest relevant check while iterating.
4. Run `make check` before handoff and report its actual result.
