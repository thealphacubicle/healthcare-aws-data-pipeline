# 2-3. Trigger, orchestration & transform: a `_manifest.json` landing in the
# raw bucket starts the Step Functions ETL (one execution per ingestion run).

locals {
  transform_steps = {
    prepare = "healthcare_pipeline.transform.handlers.prepare_run"
    clean   = "healthcare_pipeline.transform.handlers.clean"
    join    = "healthcare_pipeline.transform.handlers.join"
    publish = "healthcare_pipeline.transform.handlers.derive_and_publish"
  }

  lambda_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException",
      "Lambda.AWSLambdaException",
      "Lambda.SdkClientException",
      "Lambda.TooManyRequestsException",
    ]
    IntervalSeconds = 5
    MaxAttempts     = 3
    BackoffRate     = 2
  }]
}

resource "aws_iam_role" "transform" {
  name               = "${local.name}-transform"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "transform" {
  statement {
    sid       = "ReadRawZone"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.this["raw"].arn}/*"]
  }

  statement {
    sid     = "WriteCuratedZone"
    actions = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = [
      "${aws_s3_bucket.this["curated"].arn}/${local.curated_tables_prefix}/*",
      "${aws_s3_bucket.this["curated"].arn}/${local.curated_staging_prefix}/*",
    ]
  }

  statement {
    sid       = "ListCuratedZone"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.this["curated"].arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [for g in aws_cloudwatch_log_group.transform : "${g.arn}:*"]
  }
}

resource "aws_iam_role_policy" "transform" {
  role   = aws_iam_role.transform.id
  policy = data.aws_iam_policy_document.transform.json
}

resource "aws_cloudwatch_log_group" "transform" {
  for_each          = local.transform_steps
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "transform" {
  for_each         = local.transform_steps
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.transform.arn
  runtime          = "python3.12"
  handler          = each.value
  filename         = "${local.build_dir}/transform.zip"
  source_code_hash = filebase64sha256("${local.build_dir}/transform.zip")
  layers           = [var.aws_sdk_pandas_layer_arn]
  memory_size      = each.key == "prepare" ? 256 : var.transform_memory_mb
  timeout          = each.key == "prepare" ? 30 : 900

  environment {
    variables = {
      CURATED_BUCKET        = aws_s3_bucket.this["curated"].id
      CURATED_TABLES_PREFIX = local.curated_tables_prefix
    }
  }

  depends_on = [aws_cloudwatch_log_group.transform, aws_iam_role_policy.transform]
}

# --- State machine ---------------------------------------------------------

resource "aws_cloudwatch_log_group" "etl" {
  name              = "/aws/vendedlogs/states/${local.name}-etl"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name}-etl"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "sfn" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [for f in aws_lambda_function.transform : f.arn]
  }

  statement {
    # Log delivery APIs do not support resource-level permissions.
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn" {
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn.json
}

resource "aws_sfn_state_machine" "etl" {
  name     = "${local.name}-etl"
  role_arn = aws_iam_role.sfn.arn

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.etl.arn}:*"
    include_execution_data = false # keep row-level data out of logs
    level                  = "ERROR"
  }

  definition = jsonencode({
    Comment = "Clean, join, derive, and publish the curated Parquet table."
    StartAt = "PrepareRun"
    States = {
      PrepareRun = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = { FunctionName = aws_lambda_function.transform["prepare"].arn, "Payload.$" = "$" }
        OutputPath = "$.Payload"
        Retry      = local.lambda_retry
        Next       = "CleanDatasets"
      }
      CleanDatasets = {
        Type           = "Map"
        ItemsPath      = "$.datasets"
        MaxConcurrency = 4
        ItemSelector = {
          "run_id.$"     = "$.run_id"
          "raw_bucket.$" = "$.raw_bucket"
          "name.$"       = "$$.Map.Item.Value.name"
          "raw_key.$"    = "$$.Map.Item.Value.raw_key"
        }
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "CleanDataset"
          States = {
            CleanDataset = {
              Type       = "Task"
              Resource   = "arn:${local.partition}:states:::lambda:invoke"
              Parameters = { FunctionName = aws_lambda_function.transform["clean"].arn, "Payload.$" = "$" }
              OutputPath = "$.Payload"
              Retry      = local.lambda_retry
              End        = true
            }
          }
        }
        ResultPath = "$.cleaned"
        Next       = "JoinDatasets"
      }
      JoinDatasets = {
        Type     = "Task"
        Resource = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.transform["join"].arn
          Payload      = { "run_id.$" = "$.run_id", "cleaned.$" = "$.cleaned" }
        }
        ResultSelector = { "joined_key.$" = "$.Payload.joined_key", "rows.$" = "$.Payload.rows" }
        ResultPath     = "$.joined"
        Retry          = local.lambda_retry
        Next           = "DeriveAndPublish"
      }
      DeriveAndPublish = {
        Type     = "Task"
        Resource = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = aws_lambda_function.transform["publish"].arn
          Payload = {
            "run_id.$"      = "$.run_id"
            "ingest_date.$" = "$.ingest_date"
            "joined_key.$"  = "$.joined.joined_key"
          }
        }
        ResultSelector = { "result.$" = "$.Payload" }
        ResultPath     = "$.published"
        Retry          = local.lambda_retry
        End            = true
      }
    }
  })

  depends_on = [aws_iam_role_policy.sfn]
}

# --- S3 (via EventBridge) -> Step Functions --------------------------------

resource "aws_cloudwatch_event_rule" "manifest_created" {
  name        = "${local.name}-manifest-created"
  description = "An ingestion run finished writing files to the raw zone."

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.this["raw"].id] }
      object = { key = [{ suffix = "/_manifest.json" }] }
    }
  })
}

data "aws_iam_policy_document" "events_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "events_start_etl" {
  name               = "${local.name}-events-start-etl"
  assume_role_policy = data.aws_iam_policy_document.events_assume.json
}

resource "aws_iam_role_policy" "events_start_etl" {
  role = aws_iam_role.events_start_etl.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "states:StartExecution"
      Resource = aws_sfn_state_machine.etl.arn
    }]
  })
}

resource "aws_cloudwatch_event_target" "manifest_created" {
  rule     = aws_cloudwatch_event_rule.manifest_created.name
  arn      = aws_sfn_state_machine.etl.arn
  role_arn = aws_iam_role.events_start_etl.arn

  input_transformer {
    input_paths = {
      bucket = "$.detail.bucket.name"
      key    = "$.detail.object.key"
    }
    input_template = <<-JSON
      {"bucket": <bucket>, "manifest_key": <key>}
    JSON
  }
}
