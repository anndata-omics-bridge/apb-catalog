VENV_BIN := .venv/bin

.DEFAULT_GOAL := help
.PHONY: help sync format format-check lint typecheck deps test build docs check clean schema

help:  ## Show developer commands
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

sync:  ## Synchronize the locked development environment
	uv sync --frozen --group dev

format:  ## Format and autofix source and tests
	$(VENV_BIN)/ruff format src tests
	$(VENV_BIN)/ruff check --fix src tests

format-check:  ## Check formatting without changing files
	$(VENV_BIN)/ruff format --check src tests

lint:  ## Run Ruff lint checks
	$(VENV_BIN)/ruff check src tests

typecheck:  ## Run standard Pyright in strict mode
	$(VENV_BIN)/pyright

deps:  ## Validate dependency declarations
	$(VENV_BIN)/deptry .

test:  ## Run tests with branch coverage
	$(VENV_BIN)/pytest --cov --cov-branch

schema:  ## Regenerate the published snapshot JSON Schema
	$(VENV_BIN)/python -c "import json; from apb_catalog.snapshot import SCHEMA_FILE, snapshot_json_schema; open(f'src/apb_catalog/data/{SCHEMA_FILE}', 'w').write(json.dumps(snapshot_json_schema(), indent=2) + '\\n')"

build:  ## Build and validate source and wheel distributions
	uv build
	$(VENV_BIN)/twine check dist/*

docs:  ## Build user documentation with strict warnings
	uv run --frozen --group docs zensical build --clean --strict

check:  ## Run every merge-blocking quality gate
	uv lock --check
	$(MAKE) format-check lint typecheck deps test build docs

clean:  ## Remove generated build and quality artifacts
	$(VENV_BIN)/python -c "import shutil; [shutil.rmtree(path, ignore_errors=True) for path in ('build', 'dist', 'public', '.pytest_cache', '.ruff_cache')]"
