variable "env" { type = string }
variable "alb_dns_name" { type = string }

# Shared secret sent to the ALB as X-Origin-Verify on every origin request.
variable "origin_verify_secret" {
  type      = string
  sensitive = true
}

# IPv4 CIDRs allowed through the edge. Empty (the default) = no CloudFront
# Function is attached, so this environment is open to all viewers.
variable "allowed_cidrs" {
  type    = list(string)
  default = []
}

# Custom hostnames served by this distribution (e.g. ["smart.hplink.io"]).
# Empty (the default) = the *.cloudfront.net name only, as before.
variable "aliases" {
  type    = list(string)
  default = []
}

# us-east-1 ACM certificate covering every alias. Empty = CloudFront default cert.
variable "acm_certificate_arn" {
  type    = string
  default = ""
}

# Route 53 zone to write the alias A/AAAA records into. Required when aliases is set.
variable "route53_zone_id" {
  type    = string
  default = ""
}
