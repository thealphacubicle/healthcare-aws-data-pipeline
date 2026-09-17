# Healthcare AWS Data Pipeline

## Engineering rules

- Use Python 3.12 and manage Python dependencies with `uv`.
- Keep healthcare data handling privacy-preserving: never commit real PHI,
  credentials, tokens, or production identifiers.
- Prefer small, typed, testable modules with clear boundaries between data
  processing and AWS integration.
- Run `make check` before submitting changes and add focused tests for behavior
  changes.
- Format Terraform with `terraform fmt` and keep state out of the repository.
- Treat AWS IAM permissions, encryption, auditability, and least privilege as
  first-class design concerns.

Use the custom agents in `.github/agents/` when a task benefits from a focused
software engineering, architecture, testing, or AWS design perspective.