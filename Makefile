.DEFAULT_GOAL := setup

PYTHON_VERSION := 3.12.11
UV := uv
AWS_REGION ?= us-east-1

.PHONY: setup login logout deploy destroy install test lint fmt fmt-check \
	terraform-fmt terraform-fmt-check check build terraform-validate \
	register-table-ddl _require-aws

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
	if [ ! -f infra/terraform.tfvars ]; then \
		cp infra/terraform.tfvars.example infra/terraform.tfvars; \
		printf '\033[36m==>\033[0m Created infra/terraform.tfvars — fill it in before make deploy\n'; \
	fi; \
	$(MAKE) --no-print-directory _ensure-clis; \
	if ! $(MAKE) --no-print-directory _require-aws; then \
		printf '\033[33mAWS login skipped.\033[0m make deploy will require it.\n'; \
	fi; \
	printf '\033[32m\nSetup complete.\033[0m Activate with: source .venv/bin/activate\n'

# Used by setup, deploy, and destroy. `make login` always runs aws configure.
login:
	@set -eu; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf '\033[31mERROR\033[0m AWS CLI is required. Run make setup.\n'; \
		exit 1; \
	fi; \
	aws configure; \
	aws sts get-caller-identity

# For setup/deploy/destroy: use existing credentials, otherwise aws configure.
_require-aws:
	@set -eu; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf '\033[31mERROR\033[0m AWS CLI is required. Run make setup.\n'; \
		exit 1; \
	fi; \
	if aws sts get-caller-identity >/dev/null 2>&1; then \
		aws sts get-caller-identity; \
		exit 0; \
	fi; \
	$(MAKE) --no-print-directory login

logout:
	@set -eu; \
	if ! command -v aws >/dev/null 2>&1; then \
		printf '\033[31mERROR\033[0m AWS CLI is required. Run make setup.\n'; \
		exit 1; \
	fi; \
	if aws sso logout >/dev/null 2>&1; then \
		printf '\033[32mLogged out of AWS SSO.\033[0m\n'; \
	else \
		printf 'No AWS SSO session to clear.\n'; \
	fi

deploy: _require-aws build
	@set -eu; \
	$(tf-init); \
	terraform -chdir=infra apply; \
	ingest=$$(terraform -chdir=infra output -raw ingest_function); \
	etl=$$(terraform -chdir=infra output -raw etl_function); \
	workgroup=$$(terraform -chdir=infra output -raw athena_workgroup); \
	aws lambda delete-function-concurrency --function-name "$$ingest" >/dev/null 2>&1 || true; \
	aws lambda delete-function-concurrency --function-name "$$etl" >/dev/null 2>&1 || true; \
	aws athena update-work-group --work-group "$$workgroup" --state ENABLED >/dev/null 2>&1 || true

destroy: _require-aws build
	@set -eu; \
	$(tf-init); \
	terraform -chdir=infra destroy; \
	$(MAKE) --no-print-directory logout

install:
	uv sync --locked --python $(PYTHON_VERSION)

test:
	uv run pytest

lint:
	uv run ruff check .

fmt:
	uv run ruff format .
	terraform fmt -recursive

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

.PHONY: _ensure-clis

_ensure-clis:
	@set -eu; \
	_install() { \
		name=$$1; formula=$$2; \
		if command -v "$$name" >/dev/null 2>&1; then \
			printf '\033[36m==>\033[0m %s already installed\n' "$$name"; \
			return 0; \
		fi; \
		if ! command -v brew >/dev/null 2>&1; then \
			printf '\033[31mERROR\033[0m %s is required. Install Homebrew or %s, then rerun make setup.\n' "$$name" "$$name"; \
			exit 1; \
		fi; \
		printf '\033[36m==>\033[0m Installing %s...\n' "$$formula"; \
		brew install "$$formula"; \
	}; \
	_install terraform hashicorp/tap/terraform; \
	_install aws awscli

# Create the S3 state bucket if needed, then terraform init.
define tf-init
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
		-backend-config="encrypt=true"
endef
