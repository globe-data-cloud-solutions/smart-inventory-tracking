variable "env"        { type = string }
variable "account_id" { type = string }

# Amazon Managed Service for Prometheus (AMP)
resource "aws_prometheus_workspace" "main" {
  alias = "smart-${var.env}"
}

# Amazon Managed Grafana (AMG)
resource "aws_grafana_workspace" "main" {
  name                     = "smart-${var.env}"
  account_access_type      = "CURRENT_ACCOUNT"
  authentication_providers = ["AWS_SSO"]
  permission_type          = "SERVICE_MANAGED"
  data_sources             = ["PROMETHEUS", "CLOUDWATCH", "XRAY"]
}

# CloudWatch alarms for outbox health
resource "aws_cloudwatch_metric_alarm" "outbox_depth" {
  alarm_name          = "smart-${var.env}-outbox-depth"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "OutboxPendingDepth"
  namespace           = "SMART/Outbox"
  period              = 60
  statistic           = "Maximum"
  threshold           = 500
  alarm_description   = "Outbox PENDING row count exceeded 500 — worker may be lagging"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "outbox_max_retries" {
  alarm_name          = "smart-${var.env}-outbox-max-retries"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "OutboxRowsNearMaxRetry"
  namespace           = "SMART/Outbox"
  period              = 60
  statistic           = "Sum"
  threshold           = 1
  alarm_description   = "Outbox row approaching max retries (attempts >= 4)"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_sns_topic" "alerts" {
  name = "smart-${var.env}-alerts"
}

output "prometheus_workspace_id" { value = aws_prometheus_workspace.main.id }
output "grafana_workspace_id"    { value = aws_grafana_workspace.main.id }
