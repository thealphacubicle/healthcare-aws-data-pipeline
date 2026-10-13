# Bootstrap

One-time setup, run by hand with your own AWS credentials before the root
`infra/` module or the `deploy.yml` GitHub Actions workflow can be used. It
creates:

- An S3 bucket + DynamoDB table so the root module's Terraform state is
  remote and lockable instead of a local `.tfstate` file.
- An IAM OIDC role that GitHub Actions can assume to deploy, without storing
  AWS access keys as repo secrets.

This module's own state is local on purpose: it rarely changes, and the
remote backend it creates has to exist before anything can use it.

## Run it

```bash
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply \
  -var="github_org=<your-github-org-or-username>"
```

If your AWS account already has a GitHub Actions OIDC provider (e.g. from
another project — AWS allows only one per URL per account), add:

```bash
  -var="create_oidc_provider=false" \
  -var="existing_oidc_provider_arn=arn:aws:iam::<account-id>:oidc-provider/token.actions.githubusercontent.com"
```

## Use the outputs

```bash
terraform -chdir=infra/bootstrap output
```

- `tf_state_bucket` / `tf_lock_table` → fill in `infra/backend.hcl` (copy
  from `infra/backend.hcl.example`) for both local and CI Terraform runs.
- `github_deploy_role_arn` → add as the `AWS_DEPLOY_ROLE_ARN` secret in the
  GitHub repo (Settings → Secrets and variables → Actions). See
  `infra/README.md` for the full CI/CD setup.
