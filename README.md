# healthcare-aws-data-pipeline
An AWS data pipeline for healthcare-related data.

## Architecture

```
Google Drive folder
   │  EventBridge schedule → ingest Lambda (incremental, watermark in S3)
   ▼
S3 raw zone   ingest_date=YYYY-MM-DD/run_id=…/<file>.csv + _manifest.json
   │  ingest Lambda invokes the ETL Lambda directly (async, one run per ingestion)
   ▼
ETL Lambda: clean each file → join → derive → publish Parquet
   ▼
S3 curated zone   tables/patient_summary/part-<run_id>.parquet
   │  Glue Data Catalog table, registered once by hand (no crawler)
   ▼
Athena workgroup (per-query scan cap)  ◄──  Streamlit on EC2 t3.micro
                                             http://ec2-<ip>.<region>.compute.amazonaws.com
```

Guardrails: a $5 monthly AWS Budget with a 1% email alert and a budget action
that stops the EC2 instance at 100%, plus SNS email on ingestion or ETL
failure.

| Path | Purpose |
|---|---|
| `src/healthcare_pipeline/pipeline_config.json` | Declares the master file, supporting files, column types, and derived fields |
| `src/healthcare_pipeline/ingest.py` | Drive → raw zone Lambda |
| `src/healthcare_pipeline/transform/` | Clean, join, derive, and Parquet steps; `etl.py` runs them in sequence |
| `src/healthcare_pipeline/catalog.py`, `scripts/register_table.py` | One-time Glue table registration (DDL or `boto3`) |
| `app/streamlit_app.py` | Dashboard |
| `infra/` | Terraform for everything above; see [`infra/README.md`](infra/README.md) to deploy |

### Adding the supporting files

`pipeline_config.json` ships with a synthetic example: a `patients` master and
two supporting files. To add your files:

1. Add one entry per file under `supporting`. Give it the exact Drive file
   name, the join key column, and every column you need with its type
   (`string`, `bigint`, `double`, `boolean`, `date`, `timestamp`). Column names
   are matched after they're normalized to snake_case, and must be unique
   across files.
2. Each supporting file must have **one row per join key**. The pipeline fails
   loudly rather than fan out rows. Pre-aggregate detail files (for example,
   one row per encounter) to one row per key first.
3. Add any derived columns under `derived` and implement them in
   `transform/derive.py`.
4. Run `make test`, then re-register the table with
   `scripts/register_table.py --apply --replace`.

## Quickstart

This project uses Python 3.12.11, `uv` for Python and dependency management,
Ruff for linting and formatting, pytest for tests, and Terraform for AWS
infrastructure. The pinned Python version is recorded in `.python-version` and
the dependency resolution is recorded in `uv.lock`.

### 1. Install prerequisites

For a local checkout, install:

- Python tooling: [uv](https://docs.astral.sh/uv/)
- GNU Make
- Terraform 1.8 or later
- Git

Python 3.12.11 does not need to be installed separately. `make setup` asks `uv`
to install that exact version when it is not already available. No AWS account,
credentials, or real healthcare data are needed to complete setup.

### 2. Bootstrap the project

From the repository root, run:

```bash
make setup
```

This single command:

1. Checks that `uv` is available.
2. Installs Python 3.14.2 through `uv` if necessary.
3. Recreates `.venv` with Python 3.14.2.
4. Installs the locked runtime and development dependencies from `pyproject.toml`.
5. Installs the repository's pre-commit hook.

The command is safe to rerun. It replaces only the local `.venv`; source files,
Terraform state, and project data are not modified.

### 3. Activate and verify

Activation is optional because the Makefile uses `uv run`, but it can be useful
when working interactively:

```bash
source .venv/bin/activate
python --version       # Python 3.12.11
make test
make check
```

`make check` runs Ruff linting, checks Python formatting, and checks recursive
Terraform formatting. `make test` runs the pytest suite. The pre-commit hook
runs Ruff and Terraform formatting automatically before commits.

### Codespaces and dev containers

Opening the repository in GitHub Codespaces or a VS Code dev container uses
`.devcontainer/devcontainer.json`. It provisions Python, `uv`, Terraform, the
AWS CLI, and GitHub CLI, then runs `make setup` automatically. After the
container finishes creating, use `make test` or `make check` from the
integrated terminal.

### Common commands

```bash
make setup              # Install Python, dependencies, and developer tooling
make test               # Run the test suite
make lint               # Run Ruff checks
make fmt                # Format Python files with Ruff
make terraform-fmt      # Format Terraform files
make check              # Run lint, Python format, and Terraform format checks
make build              # Build Lambda and dashboard bundles into build/
make terraform-validate # Build, then terraform init/validate in infra/
```

The repository includes shared Copilot custom agents under `.github/agents/`
for software engineering, architecture, testing, and AWS solution design.
