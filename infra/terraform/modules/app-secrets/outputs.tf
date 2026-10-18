# Secret ARNs keyed by path under smart/<env>/ (e.g. "jwt/secret").
output "arns" {
  value = { for k, s in aws_secretsmanager_secret.app : k => s.arn }
}
