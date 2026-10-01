variable "aws_region" {
  description = "AWS region for the deployment."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Short project name used in resource names."
  type        = string
  default     = "healthcare-pipeline"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev)."
  type        = string
  default     = "dev"
}

variable "alert_email" {
  description = "Email address for budget alerts and pipeline failure notifications."
  type        = string
}

variable "drive_folder_id" {
  description = "ID of the Google Drive folder holding the master and supporting CSVs."
  type        = string
}

variable "google_credentials_parameter_name" {
  description = "SSM Parameter Store SecureString holding the Google service account JSON. Created outside Terraform so the secret never enters state."
  type        = string
  default     = "/healthcare-pipeline/google-service-account"
}

variable "ingest_schedule_expression" {
  description = "Schedule expression (EventBridge rule) for the Drive ingestion Lambda."
  type        = string
  default     = "cron(0 6 * * ? *)"
}

variable "aws_sdk_pandas_layer_arn" {
  description = "ARN of the AWS-managed 'AWSSDKPandas-Python312' Lambda layer for this region (provides pandas and pyarrow). Look up the current ARN at https://aws-sdk-pandas.readthedocs.io/en/stable/layers.html."
  type        = string
}

variable "transform_memory_mb" {
  description = "Memory for the ETL Lambda. Raise if the joined dataset grows."
  type        = number
  default     = 2048
}

variable "glue_database_name" {
  description = "Glue Data Catalog database that holds the manually registered curated table."
  type        = string
  default     = "healthcare"
}

variable "curated_table_name" {
  description = "Curated table name; must match output_table in pipeline_config.json."
  type        = string
  default     = "patient_summary"
}

variable "athena_bytes_scanned_cutoff" {
  description = "Per-query scan limit enforced by the Athena workgroup, in bytes (minimum 10 MB)."
  type        = number
  default     = 1073741824
}

variable "dashboard_instance_type" {
  description = "EC2 instance type for the Streamlit dashboard."
  type        = string
  default     = "t3.micro"
}

variable "dashboard_allowed_cidrs" {
  description = "CIDR blocks allowed to open the dashboard over HTTP (port 80). Defaults to the whole internet; narrow to e.g. [\"<your-ip>/32\"] to restrict it."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "monthly_budget_usd" {
  description = "Monthly AWS Budget limit in USD. The budget action stops the dashboard instance when actual spend reaches it."
  type        = string
  default     = "5"
}

variable "budget_alert_threshold_percent" {
  description = "Percentage of the budget at which an email alert is sent."
  type        = number
  default     = 1
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for Lambda logs."
  type        = number
  default     = 14
}
