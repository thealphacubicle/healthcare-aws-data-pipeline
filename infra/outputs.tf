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

output "state_machine_arn" {
  description = "Step Functions ETL state machine."
  value       = aws_sfn_state_machine.etl.arn
}

output "dashboard_instance_id" {
  description = "EC2 instance running Streamlit."
  value       = aws_instance.dashboard.id
}

output "dashboard_port_forward_command" {
  description = "Open the dashboard at http://localhost:8501 through SSM, with no inbound port."
  value       = "aws ssm start-session --region ${var.aws_region} --target ${aws_instance.dashboard.id} --document-name AWS-StartPortForwardingSession --parameters portNumber=8501,localPortNumber=8501"
}
