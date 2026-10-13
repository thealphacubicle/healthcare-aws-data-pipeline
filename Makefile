.DEFAULT_GOAL := setup

PYTHON_VERSION := 3.12.11
UV := uv

.PHONY: setup install test lint fmt fmt-check terraform-fmt terraform-fmt-check check build \
	terraform-validate register-table-ddl

setup:
	@set -eu; \
	if ! command -v $(UV) >/dev/null 2>&1; then \
		printf '\033[31mERROR\033[0m uv is required. Install it from https://docs.astral.sh/uv/\n'; \
		exit 1; \
	fi; \
	printf '\033[36m==>\033[0m Installing Python $(PYTHON_VERSION) if needed...\n'; \
	$(UV) python install $(PYTHON_VERSION); \
	printf '\033[36m==>\033[0m Creating or updating the Python environment...\n'; \
	$(UV) venv --clear --python $(PYTHON_VERSION); \
	printf '\033[36m==>\033[0m Installing project and development dependencies...\n'; \
	$(UV) sync --locked --python $(PYTHON_VERSION); \
	printf '\033[36m==>\033[0m Installing the pre-commit hook...\n'; \
	$(UV) run pre-commit install; \
	printf '\033[32m\nSetup complete.\033[0m Activate with: source .venv/bin/activate\n'

install:
	uv sync --locked --python $(PYTHON_VERSION)

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .

terraform-fmt:
	terraform fmt -recursive

fmt-check:
	uv run ruff format --check .

terraform-fmt-check:
	terraform fmt -check -recursive

check: lint fmt-check terraform-fmt-check

build:
	uv run python scripts/build_lambdas.py

terraform-validate: build
	terraform -chdir=infra init -backend=false -input=false
	terraform -chdir=infra validate

# Usage: make register-table-ddl BUCKET=<curated-bucket> [DATABASE=healthcare]
register-table-ddl:
	uv run python scripts/register_table.py --database $(or $(DATABASE),healthcare) --bucket $(BUCKET)
