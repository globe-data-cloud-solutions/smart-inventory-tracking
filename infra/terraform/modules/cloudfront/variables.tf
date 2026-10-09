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
