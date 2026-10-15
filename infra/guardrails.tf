# 7. Guardrails: a monthly cost budget (default $5) that emails at 1% and, at
# 100% actual spend, shuts down pipeline compute: stop EC2, disable the ingest
# schedule, freeze the ingest/ETL Lambdas, and disable the Athena workgroup.
# S3 and Glue stay so data is not deleted.
#
# Budgets data refreshes a few times a day, so this is a backstop, not a
# real-time kill switch. Free Tier usage alerts have no API; turn them on in
# Billing and Cost Management > Billing preferences (see infra/README.md).

resource "aws_budgets_budget" "monthly" {
  name         = "${local.name}-monthly"
  budget_type  = "COST"
  limit_amount = var.monthly_budget_usd
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_alert_threshold_percent
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.budget.arn]
  }
}

resource "aws_sns_topic" "budget" {
  name = "${local.name}-budget"
}

data "aws_iam_policy_document" "budget_sns" {
  statement {
    sid     = "AllowBudgetsPublish"
    actions = ["sns:Publish"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    resources = [aws_sns_topic.budget.arn]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_sns_topic_policy" "budget" {
  arn    = aws_sns_topic.budget.arn
  policy = data.aws_iam_policy_document.budget_sns.json
}

data "aws_iam_policy_document" "budget_shutdown_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "budget_shutdown" {
  name               = "${local.name}-budget-shutdown"
  assume_role_policy = data.aws_iam_policy_document.budget_shutdown_assume.json
}

data "aws_iam_policy_document" "budget_shutdown" {
  statement {
    sid       = "StopDashboard"
    actions   = ["ec2:StopInstances"]
    resources = [aws_instance.dashboard.arn]
  }

  statement {
    sid       = "DisableIngestSchedule"
    actions   = ["events:DisableRule"]
    resources = [aws_cloudwatch_event_rule.ingest_schedule.arn]
  }

  statement {
    sid       = "FreezePipelineLambdas"
    actions   = ["lambda:PutFunctionConcurrency"]
    resources = [aws_lambda_function.ingest.arn, aws_lambda_function.etl.arn]
  }

  statement {
    sid       = "DisableAthena"
    actions   = ["athena:UpdateWorkGroup"]
    resources = [aws_athena_workgroup.this.arn]
  }

  statement {
    sid       = "WriteLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.budget_shutdown.arn}:*"]
  }
}

resource "aws_iam_role_policy" "budget_shutdown" {
  role   = aws_iam_role.budget_shutdown.id
  policy = data.aws_iam_policy_document.budget_shutdown.json
}

resource "aws_cloudwatch_log_group" "budget_shutdown" {
  name              = "/aws/lambda/${local.name}-budget-shutdown"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "budget_shutdown" {
  function_name    = "${local.name}-budget-shutdown"
  role             = aws_iam_role.budget_shutdown.arn
  runtime          = "python3.12"
  handler          = "healthcare_pipeline.budget.handler"
  filename         = "${local.build_dir}/budget.zip"
  source_code_hash = filebase64sha256("${local.build_dir}/budget.zip")
  memory_size      = 128
  timeout          = 60

  environment {
    variables = {
      DASHBOARD_INSTANCE_ID = aws_instance.dashboard.id
      INGEST_RULE_NAME      = aws_cloudwatch_event_rule.ingest_schedule.name
      PIPELINE_FUNCTIONS    = "${aws_lambda_function.ingest.function_name},${aws_lambda_function.etl.function_name}"
      ATHENA_WORKGROUP      = aws_athena_workgroup.this.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.budget_shutdown, aws_iam_role_policy.budget_shutdown]
}

resource "aws_lambda_permission" "budget_sns" {
  statement_id  = "AllowBudgetSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.budget_shutdown.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.budget.arn
}

resource "aws_sns_topic_subscription" "budget_shutdown" {
  topic_arn = aws_sns_topic.budget.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.budget_shutdown.arn
}

data "aws_iam_policy_document" "budgets_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "budget_action" {
  name               = "${local.name}-budget-action"
  assume_role_policy = data.aws_iam_policy_document.budgets_assume.json
}

resource "aws_iam_role_policy_attachment" "budget_action" {
  role       = aws_iam_role.budget_action.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSBudgetsActions_RolePolicyForResourceAdministrationWithSSM"
}

# Native budget action as a backup if the shutdown Lambda is slow or fails.
resource "aws_budgets_budget_action" "stop_dashboard" {
  budget_name        = aws_budgets_budget.monthly.name
  action_type        = "RUN_SSM_DOCUMENTS"
  approval_model     = "AUTOMATIC"
  notification_type  = "ACTUAL"
  execution_role_arn = aws_iam_role.budget_action.arn

  action_threshold {
    action_threshold_type  = "PERCENTAGE"
    action_threshold_value = 100
  }

  definition {
    ssm_action_definition {
      action_sub_type = "STOP_EC2_INSTANCES"
      instance_ids    = [aws_instance.dashboard.id]
      region          = var.aws_region
    }
  }

  subscriber {
    address           = var.alert_email
    subscription_type = "EMAIL"
  }

  depends_on = [aws_iam_role_policy_attachment.budget_action]
}
