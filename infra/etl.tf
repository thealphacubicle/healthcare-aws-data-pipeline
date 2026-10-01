# 2-3. Transform: one ETL Lambda that runs clean -> join -> derive -> publish
# in sequence. The ingest Lambda invokes it directly (asynchronously) after
# writing a run's manifest; no Step Functions, EventBridge rule, or S3
# notification is involved.

resource "aws_iam_role" "etl" {
  name               = "${local.name}-etl"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "etl" {
  statement {
    sid       = "ReadRawZone"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["raw"].arn}/*"]
  }

  statement {
    sid       = "WriteCuratedTables"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.this["curated"].arn}/${local.curated_tables_prefix}/*"]
  }

  statement {
    sid       = "ListCuratedZone"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this["curated"].arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.etl.arn}:*"]
  }
}

resource "aws_iam_role_policy" "etl" {
  role   = aws_iam_role.etl.id
  policy = data.aws_iam_policy_document.etl.json
}

resource "aws_cloudwatch_log_group" "etl" {
  name              = "/aws/lambda/${local.name}-etl"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "etl" {
  function_name    = "${local.name}-etl"
  role             = aws_iam_role.etl.arn
  runtime          = "python3.12"
  handler          = "healthcare_pipeline.transform.etl.handler"
  filename         = "${local.build_dir}/transform.zip"
  source_code_hash = filebase64sha256("${local.build_dir}/transform.zip")
  layers           = [var.aws_sdk_pandas_layer_arn]
  memory_size      = var.transform_memory_mb
  timeout          = 900

  environment {
    variables = {
      CURATED_BUCKET        = aws_s3_bucket.this["curated"].id
      CURATED_TABLES_PREFIX = local.curated_tables_prefix
    }
  }

  depends_on = [aws_cloudwatch_log_group.etl, aws_iam_role_policy.etl]
}

# Retry a failed asynchronous run once; failures show up in CloudWatch Logs.
resource "aws_lambda_function_event_invoke_config" "etl" {
  function_name          = aws_lambda_function.etl.function_name
  maximum_retry_attempts = 1
}
