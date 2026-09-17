# healthcare-aws-data-pipeline
An AWS data pipeline for healthcare-related data.

## Quickstart

This project uses Python 3.14.2, `uv` for Python and dependency management,
Ruff for linting and formatting, pytest for tests, and Terraform for AWS
infrastructure. The pinned Python version is recorded in `.python-version` and
the dependency resolution is recorded in `uv.lock`.

### 1. Install prerequisites

For a local checkout, install:

- Python tooling: [uv](https://docs.astral.sh/uv/)
- GNU Make
- Terraform 1.8 or later
- Git

Python 3.14.2 does not need to be installed separately. `make setup` asks `uv`
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
python --version       # Python 3.14.2
make test
make check
```

`make check` runs Ruff linting, checks Python formatting, and checks recursive
Terraform formatting. `make test` runs the pytest suite. The pre-commit hook
runs Ruff and Terraform formatting automatically before commits.

### Codespaces and dev containers

Opening the repository in GitHub Codespaces or a VS Code dev container uses
`.devcontainer/devcontainer.json`. It provisions Python, `uv`, Terraform, and
GitHub CLI, then runs `make setup` automatically. After the container finishes
creating, use `make test` or `make check` from the integrated terminal.

### Common commands

```bash
make setup              # Install Python, dependencies, and developer tooling
make test               # Run the test suite
make lint               # Run Ruff checks
make fmt                # Format Python files with Ruff
make terraform-fmt      # Format Terraform files
make check              # Run lint, Python format, and Terraform format checks
```

The repository includes shared Copilot custom agents under `.github/agents/`
for software engineering, architecture, testing, and AWS solution design.
