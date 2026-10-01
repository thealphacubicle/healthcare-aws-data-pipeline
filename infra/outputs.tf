output "raw_bucket" {
  description = "S3 raw zone bucket."
  value       = aws_s3_bucket.this["raw"].id
}

output "curated_bucket" {
  description = "S3 curated zone bucket (pass to scripts/register_table.py --bucket)."
  value       = aws_s3_bucket.this["curated"].id
}

output "glue_database" {
  description = "Glue database (pass to scripts/register_table.py --database)."
  value       = aws_glue_catalog_database.this.name
}

output "athena_workgroup" {
  description = "Athena workgroup with enforced result location and scan limit."
  value       = aws_athena_workgroup.this.name
}

output "ingest_function" {
  description = "Ingestion Lambda; invoke manually for a first run."
  value       = aws_lambda_function.ingest.function_name
}

output "etl_function" {
  description = "ETL Lambda (invoked by the ingest Lambda)."
  value       = aws_lambda_function.etl.function_name
}

output "dashboard_instance_id" {
  description = "EC2 instance running Streamlit."
  value       = aws_instance.dashboard.id
}

output "dashboard_url" {
  description = "Public dashboard URL (the instance's default EC2 DNS name). Changes if the instance is stopped and started."
  value       = "http://${aws_instance.dashboard.public_dns}"
}
