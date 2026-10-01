# Failure notifications: the ingest and ETL Lambdas send failed asynchronous
# invocations to this topic (Lambda on-failure destinations), which emails
# alert_email.

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
