variable "domain_name" {
  type        = string
  description = "Public hostname served by CloudFront, e.g. smart.hplink.io"
}

variable "zone_name" {
  type        = string
  description = "Existing Route 53 public hosted zone that contains domain_name, e.g. hplink.io"

  validation {
    condition     = endswith(var.domain_name, ".${var.zone_name}")
    error_message = "domain_name must be a subdomain of zone_name."
  }
}
