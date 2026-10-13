terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "${var.project}-${var.environment}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  build_dir  = "${path.module}/../build"

  # Single source of truth for the curated table name, shared with the ETL
  # and scripts/register_table.py.
  curated_table_name = jsondecode(file("${path.module}/../src/healthcare_pipeline/pipeline_config.json")).output_table

  # Prefix inside the curated bucket for Athena table data.
  curated_tables_prefix = "tables"
}
