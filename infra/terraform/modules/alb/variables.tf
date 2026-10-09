variable "env" { type = string }
variable "vpc_id" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "certificate_arn" {
  type    = string
  default = ""
}
variable "idle_timeout" {
  type    = number
  default = 60
}

# Shared secret CloudFront injects as the X-Origin-Verify header on every
# origin request; ALB listener rules only forward requests carrying it, so
# traffic that reaches the ALB directly (bypassing CloudFront) gets the
# default 403. Lives in TF state — rotate by tainting random_password.origin_verify.
variable "origin_verify_secret" {
  type      = string
  sensitive = true
}
