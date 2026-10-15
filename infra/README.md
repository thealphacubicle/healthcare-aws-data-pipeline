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
| `guardrails.tf` | 7. $5 budget; at 100% actual spend, shut down pipeline compute |

State lives in `s3://healthcare-pipeline-tfstate-<account-id>`. `make deploy`
creates that bucket if needed. There is no DynamoDB lock table. CI only lints,
formats-checks, tests, and validates; it does not apply.

## Deploy

1. **Google API key.** The Drive folder must be shared as "Anyone with the
   link" (Viewer). In Google Cloud Console, enable the Google Drive API for a
   project, then create an API key under APIs & Services → Credentials
   (optionally restrict it to the Drive API). Store it in Parameter Store. It's
   created outside Terraform so the secret never enters state. A standard
   SecureString using the AWS managed key costs nothing:

   ```bash
   aws ssm put-parameter --type SecureString \
     --name /healthcare-pipeline/google-api-key \
     --value 'YOUR_API_KEY'
   ```

2. **Variables.** `make setup` copies `terraform.tfvars.example` to
   `terraform.tfvars` (gitignored) if needed. Fill it in.
   `aws_sdk_pandas_layer_arn` must be the current AWS SDK for pandas layer ARN
   for your region.

3. **Apply or destroy.** Both commands log in to AWS first. `make destroy`
   logs out when it finishes.

   ```bash
   make deploy
   make destroy
   make logout
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
- **Budget.** The $5 budget emails at 1% ($0.05) and at 100% actual spend
  shuts down pipeline compute: stops the dashboard EC2 instance, disables the
  ingest schedule, freezes the ingest and ETL Lambdas, and disables the Athena
  workgroup. S3 and Glue stay so data is not deleted. `make deploy` brings
  compute back. Billing data lags by hours, so spend can overshoot $5 before
  this fires. Outside Free Tier, a t3.micro (about $7.50/month) plus its
  public IPv4 address (about $3.60/month) already exceed $5, so the shutdown
  may happen partway through the month.
- **Snapshot publishing.** Each ETL run writes `part-<run_id>.parquet` and
  then deletes the previous file. A query running at that exact moment can
  briefly see both snapshots.
