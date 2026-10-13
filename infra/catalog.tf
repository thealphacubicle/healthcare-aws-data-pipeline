# 4-5. Data Catalog & query. Terraform creates only the (free) Glue database
# and the Athena workgroup. The table itself is registered once by hand with
# scripts/register_table.py; no Glue Crawler is ever created.

resource "aws_glue_catalog_database" "this" {
  name        = var.glue_database_name
  description = "Curated healthcare pipeline tables (registered manually, no crawler)."
}

resource "aws_athena_workgroup" "this" {
  name          = local.name
  force_destroy = true

  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = false
    bytes_scanned_cutoff_per_query     = var.athena_bytes_scanned_cutoff

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${aws_s3_bucket.this["athena_result"].id}/results/"

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
