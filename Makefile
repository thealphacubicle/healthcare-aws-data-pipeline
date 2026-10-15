.DEFAULT_GOAL := setup

PYTHON_VERSION := 3.12.11
UV := uv

.PHONY: setup install test lint fmt fmt-check terraform-fmt terraform-fmt-check check build \
	terraform-validate deploy register-table-ddl

AWS_REGION ?= us-east-1

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

# Applies infra/ to the current AWS account. State lives in
# s3://healthcare-pipeline-tfstate-<account-id>. CI sets CI=true so apply
# is non-interactive; locally you get the usual Terraform confirm prompt.
deploy: build
	@set -eu; \
	account_id=$$(aws sts get-caller-identity --query Account --output text); \
	bucket="healthcare-pipeline-tfstate-$${account_id}"; \
	if ! aws s3api head-bucket --bucket "$$bucket" --region "$(AWS_REGION)" 2>/dev/null; then \
		printf '\033[36m==>\033[0m Creating state bucket %s\n' "$$bucket"; \
		if [ "$(AWS_REGION)" = "us-east-1" ]; then \
			aws s3api create-bucket --bucket "$$bucket" --region "$(AWS_REGION)"; \
		else \
			aws s3api create-bucket --bucket "$$bucket" --region "$(AWS_REGION)" \
				--create-bucket-configuration "LocationConstraint=$(AWS_REGION)"; \
		fi; \
		aws s3api put-public-access-block --bucket "$$bucket" --region "$(AWS_REGION)" \
			--public-access-block-configuration \
			"BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"; \
		aws s3api put-bucket-versioning --bucket "$$bucket" --region "$(AWS_REGION)" \
			--versioning-configuration Status=Enabled; \
		aws s3api put-bucket-encryption --bucket "$$bucket" --region "$(AWS_REGION)" \
			--server-side-encryption-configuration \
			'{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'; \
	fi; \
	terraform -chdir=infra init -input=false \
		-backend-config="bucket=$$bucket" \
		-backend-config="key=healthcare-pipeline/terraform.tfstate" \
		-backend-config="region=$(AWS_REGION)" \
		-backend-config="encrypt=true"; \
	if [ -n "$${CI:-}" ]; then \
		terraform -chdir=infra apply -auto-approve -input=false; \
	else \
		terraform -chdir=infra apply -input=false; \
	fi

# Usage: make register-table-ddl BUCKET=<curated-bucket> [DATABASE=healthcare]
register-table-ddl:
	uv run python scripts/register_table.py --database $(or $(DATABASE),healthcare) --bucket $(BUCKET)
