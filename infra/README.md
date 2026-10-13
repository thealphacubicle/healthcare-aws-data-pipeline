# Terraform

Deploys the whole pipeline in one root module. Files map to the architecture
layers:

| File | Layer |
|---|---|
| `ingestion.tf` | 1. Scheduled Drive → S3 raw zone Lambda, which then invokes the ETL Lambda |
| `storage.tf` | Raw / curated / Athena results / artifacts buckets |
| `etl.tf` | 2–3. ETL Lambda: clean → join → derive → publish Parquet |
| `catalog.tf` | 4–5. Glue database (no crawler, no table) and Athena workgroup |
| `dashboard.tf` | 6. EC2 Streamlit host on a public URL |
| `guardrails.tf` | 7. $5 budget, 1% alert, stop-EC2 budget action |

State is remote: `backend.tf` declares an S3 backend (with DynamoDB locking)
left unconfigured on purpose, so the same files work for any account. Run
`infra/bootstrap` once first — see `infra/bootstrap/README.md` — to create
that bucket/table (plus the IAM role GitHub Actions deploys with), then feed
its outputs into `backend.hcl` as below.

## Deploy

0. **One-time bootstrap.** Follow `infra/bootstrap/README.md` to create the
   Terraform state bucket/lock table and the GitHub Actions deploy role.
   Copy `backend.hcl.example` to `backend.hcl` (gitignored) and fill in the
   bootstrap outputs.

1. **Google credentials.** Create a Google Cloud service account with the Drive
   API enabled, share the Drive folder with the service account's email
   (Viewer), and store its JSON key in Parameter Store. It's created outside
   Terraform so the secret never enters state. A standard SecureString using
   the AWS managed key costs nothing:

   ```bash
   aws ssm put-parameter --type SecureString \
     --name /healthcare-pipeline/google-service-account \
     --value file://service-account.json
   ```

2. **Variables.** `cp terraform.tfvars.example terraform.tfvars` and fill it
   in. `aws_sdk_pandas_layer_arn` must be the current AWS SDK for pandas layer
   ARN for your region.

3. **Build and apply.**

   ```bash
   make build                                    # build/ingest.zip, transform.zip, app.zip
   terraform -chdir=infra init -backend-config=backend.hcl
   terraform -chdir=infra apply
   ```

4. **Register the curated table (one time).** Print the DDL and run it in the
   Athena query editor (select the `healthcare-pipeline-dev` workgroup), or add
   `--apply` to call `glue.create_table()` directly:

   ```bash
   uv run python scripts/register_table.py \
     --database "$(terraform -chdir=infra output -raw glue_database)" \
     --bucket "$(terraform -chdir=infra output -raw curated_bucket)"
   ```

   Re-run with `--apply --replace` only when `pipeline_config.json` changes the
   output columns.

5. **First run.** Wait for the schedule, or invoke ingestion manually:

   ```bash
   aws lambda invoke --function-name "$(terraform -chdir=infra output -raw ingest_function)" out.json
   ```

   After writing the manifest it invokes the ETL Lambda directly. Check
   progress in the `/aws/lambda/healthcare-pipeline-dev-etl` log group.

6. **Open the dashboard** at `terraform -chdir=infra output -raw dashboard_url`.
   That's the instance's default EC2 public DNS name on plain HTTP, port 80,
   with no domain or certificate. First boot takes a few minutes while the
   instance installs Streamlit. After changing the app, run `make build` and
   `apply`, then `sudo systemctl restart dashboard` on the instance (connect
   with Session Manager from the EC2 console).

7. **Free Tier alerts.** There's no API for this. Turn it on in the console:
   Billing and Cost Management → Billing preferences → Alert preferences →
   *Receive AWS Free Tier alerts*.

## Cost notes and caveats

- **No Glue Crawler, no orchestration service, no idle compute.** Lambda,
  Athena and S3 are billed per use. Athena scans only the columns a query references in the
  Parquet file, has a 10 MB minimum per query, and this workgroup refuses any
  query over `athena_bytes_scanned_cutoff` (1 GB by default). The dashboard
  caches results for an hour.
- **Direct Lambda chaining.** The ingest Lambda invokes the ETL Lambda
  asynchronously, so ingestion finishes right away. A failed run is retried once.
  There are no failure emails, so check the Lambda logs in CloudWatch if the
  dashboard looks stale. The only EventBridge piece left is the
  ingestion schedule, which is the standard (free) way to run a Lambda on a
  timer. The ETL runs every step in one invocation, so the whole dataset must
  fit in Lambda memory (`transform_memory_mb`, up to 10 GB) and finish within
  15 minutes.
- **Public dashboard.** Anyone with the URL can view it, because Streamlit has
  no login. Set `dashboard_allowed_cidrs = ["<your-ip>/32"]` to restrict it. The
  URL changes whenever the instance is stopped and started, for example by the
  budget action. An Elastic IP would keep it fixed but is billed even while the
  instance is stopped.
- **Budget.** The $5 budget emails at 1% ($0.05) and stops the EC2 instance
  when actual spend reaches $5. Outside Free Tier, a t3.micro (about
  $7.50/month) plus its public IPv4 address (about $3.60/month) cost more than
  $5, so the action may stop the dashboard partway through the month. Start it
  again from the EC2 console. The action stops only the EC2 instance; S3,
  Lambda and Athena keep running.
- **Budgets aren't real time.** Billing data refreshes a few times a day, so
  spend can overshoot before an alert or action fires.
- **Snapshot publishing.** Each ETL run writes `part-<run_id>.parquet` and
  then deletes the previous file. A query running at that exact moment can
  briefly see both snapshots.

## CI/CD (GitHub Actions)

`.github/workflows/ci.yml` already runs on every push/PR: lint, format
checks, tests, build, and `terraform validate`. `.github/workflows/deploy.yml`
goes further and actually deploys: it plans on pull requests (and posts the
plan as a PR comment) and applies on merge to `main`, authenticating to AWS
via OIDC — no long-lived AWS keys stored in GitHub.

### One-time setup

1. **Bootstrap AWS.** Run `infra/bootstrap` once with your own AWS
   credentials (see `infra/bootstrap/README.md`). It creates the Terraform
   state bucket/lock table and an IAM role GitHub Actions can assume.
2. **Repo secret** (Settings → Secrets and variables → Actions → *Secrets*):
   | Name | Value |
   |---|---|
   | `AWS_DEPLOY_ROLE_ARN` | bootstrap output `github_deploy_role_arn` |
3. **Repo variables** (same page → *Variables*):
   | Name | Value |
   |---|---|
   | `AWS_REGION` | e.g. `us-east-1` |
   | `TF_STATE_BUCKET` | bootstrap output `tf_state_bucket` |
   | `TF_STATE_DYNAMODB_TABLE` | bootstrap output `tf_lock_table` |
   | `ALERT_EMAIL` | same as `terraform.tfvars` |
   | `DRIVE_FOLDER_ID` | same as `terraform.tfvars` |
   | `AWS_SDK_PANDAS_LAYER_ARN` | same as `terraform.tfvars` |
4. **Recommended: require approval before apply.** Create a GitHub
   Environment named `production` (Settings → Environments) and add yourself
   as a required reviewer. `deploy.yml`'s apply job targets that environment,
   so merges to `main` will pause for manual approval before touching real
   AWS resources.

### Still manual, by design

- The Google service account JSON in Parameter Store (deploy step 1) — a
  secret that should never pass through Terraform state or CI logs.
- `scripts/register_table.py --apply --replace` after changing
  `pipeline_config.json`'s output columns — it's a destructive, infrequent
  schema change, not something to run on every merge.
- Approving the `production` environment deployment itself, if you set up
  the required reviewer step above.
