output "certificate_arn" {
  description = "Validated ACM certificate ARN for the CloudFront viewer certificate"
  value       = aws_acm_certificate_validation.this.certificate_arn
}

output "zone_id" {
  description = "Route 53 hosted zone ID the alias record is written into"
  value       = data.aws_route53_zone.this.zone_id
}
