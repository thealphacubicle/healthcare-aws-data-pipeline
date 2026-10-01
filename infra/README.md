# Terraform

Deploys the whole pipeline in one root module. Files map to the architecture
layers:

| File | Layer |
|---|---|
| `ingestion.tf` | 1. Scheduled Drive → S3 raw zone Lambda |
| `storage.tf` | Raw / curated / Athena results / artifacts buckets, S3 → EventBridge |
| `orchestration.tf` | 2–3. Manifest trigger → Step Functions → transform Lambdas |
| `catalog.tf` | 4–5. Glue database (no crawler, no table) and Athena workgroup |
| `dashboard.tf` | 6. EC2 Streamlit host |
| `guardrails.tf` | 7. $0.01 budget, 1% alert, stop-EC2 budget action |
| `alerts.tf` | SNS email for ingestion and ETL failures |

State is local by default. Configure a remote backend before any shared or
production deployment.

## Deploy

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
   make build                      # build/ingest.zip, transform.zip, app.zip
   terraform -chdir=infra init
   terraform -chdir=infra apply
   ```

   Confirm the SNS subscription email AWS sends to `alert_email`.

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

   The manifest it writes starts the Step Functions ETL automatically.

6. **Open the dashboard.** No inbound port is open by default. With the
   [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
   installed, run the command from
   `terraform -chdir=infra output -raw dashboard_port_forward_command` and
   browse to <http://localhost:8501>. First boot takes a few minutes while the
   instance installs Streamlit. After changing the app, `make build`, `apply`,
   then `sudo systemctl restart dashboard` on the instance.

7. **Free Tier alerts.** There's no API for this. Turn it on in the console:
   Billing and Cost Management → Billing preferences → Alert preferences →
   *Receive AWS Free Tier alerts*.

## Cost notes and caveats

- **No Glue Crawler, no idle compute.** Lambda, Step Functions, Athena and S3
  are billed per use. Athena scans only the columns a query references in the
  Parquet file, has a 10 MB minimum per query, and this workgroup refuses any
  query over `athena_bytes_scanned_cutoff` (1 GB by default). The dashboard
  caches results for an hour.
- **S3 can't start Step Functions directly.** Its event notifications only
  target SNS, SQS or Lambda. The raw bucket sends events to EventBridge instead
  (free for S3 events), and a rule matches only `*/_manifest.json`. That way one
  ingestion run of 16 files starts one execution, not 16.
- **Step Functions free tier** is 4,000 state transitions a month. One run
  uses roughly 5 + 3 × (number of datasets), so about 53 with 16 files. That
  covers a daily schedule.
- **A $0.01 budget trips almost immediately.** Any billable usage (an S3
  request, an Athena query, or the EC2 public IPv4 address at about
  $0.005/hour where Free Tier doesn't cover it) crosses $0.01. Expect the 1%
  alert on day one and the stop-EC2 action soon after. Raise
  `monthly_budget_usd` if you want the dashboard to stay up. The action stops
  only the EC2 instance; S3, Lambda and Athena keep running.
- **Budgets aren't real time.** Billing data refreshes a few times a day, so
  spend can overshoot before an alert or action fires.
- **Snapshot publishing.** Each ETL run writes `part-<run_id>.parquet` and
  then deletes the previous file. A query running at that exact moment can
  briefly see both snapshots.
