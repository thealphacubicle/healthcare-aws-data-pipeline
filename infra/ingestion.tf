# 1. Source & ingestion: scheduled Lambda pulls new/changed Drive files into
# the raw bucket. Run `make build` first to produce build/ingest.zip.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest" {
  name               = "${local.name}-ingest"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ingest" {
  statement {
    sid       = "WriteRawZone"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.this["raw"].arn}/*"]
  }

  statement {
    # Lets GetObject on the not-yet-created state file return NoSuchKey
    # instead of AccessDenied.
    sid       = "ListRawZone"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this["raw"].arn]
  }

  statement {
    sid       = "ReadGoogleCredentials"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:${local.partition}:ssm:${var.aws_region}:${local.account_id}:parameter/${trimprefix(var.google_credentials_parameter_name, "/")}"]
  }

  statement {
    sid       = "NotifyOnFailure"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingest" {
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${local.name}-ingest"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "ingest" {
  function_name    = "${local.name}-ingest"
  role             = aws_iam_role.ingest.arn
  runtime          = "python3.12"
  handler          = "healthcare_pipeline.ingest.handler"
  filename         = "${local.build_dir}/ingest.zip"
  source_code_hash = filebase64sha256("${local.build_dir}/ingest.zip")
  memory_size      = 512
  timeout          = 300

  # Never run two ingestions at once; they would race on the watermark.
  reserved_concurrent_executions = 1

  environment {
    variables = {
      RAW_BUCKET                   = aws_s3_bucket.this["raw"].id
      DRIVE_FOLDER_ID              = var.drive_folder_id
      GOOGLE_CREDENTIALS_PARAMETER = var.google_credentials_parameter_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.ingest, aws_iam_role_policy.ingest]
}

resource "aws_lambda_function_event_invoke_config" "ingest" {
  function_name          = aws_lambda_function.ingest.function_name
  maximum_retry_attempts = 1

  destination_config {
    on_failure {
      destination = aws_sns_topic.alerts.arn
    }
  }
}

resource "aws_cloudwatch_event_rule" "ingest_schedule" {
  name                = "${local.name}-ingest-schedule"
  description         = "Incremental Google Drive pull into the raw zone."
  schedule_expression = var.ingest_schedule_expression
}

resource "aws_cloudwatch_event_target" "ingest_schedule" {
  rule = aws_cloudwatch_event_rule.ingest_schedule.name
  arn  = aws_lambda_function.ingest.arn
}

resource "aws_lambda_permission" "ingest_schedule" {
  statement_id  = "AllowEventBridgeSchedule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.ingest_schedule.arn
}
