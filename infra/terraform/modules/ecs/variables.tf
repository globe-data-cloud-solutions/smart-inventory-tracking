variable "env" { type = string }
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }
variable "account_id" { type = string }

# Services with a live task def + aws_ecs_service in this env. order/logistics/
# analytics/notification/sync are stubs (image/CMD exist, not deployed) — add
# to this list per env to deploy.
variable "enabled_services" { type = list(string) }

variable "service_sizing" {
  description = "Per-service Fargate sizing; \"default\" key is the fallback for any enabled_services entry without its own override."
  type = map(object({
    cpu             = number
    memory          = number
    desired_count   = number
    web_concurrency = number
  }))
}

variable "worker_sizing" {
  type = object({
    cpu    = number
    memory = number
  })
}

variable "beat_sizing" {
  type = object({
    cpu    = number
    memory = number
  })
}

variable "email_delivery_mode" { type = string }
variable "feature_lot_tracking" {
  type        = bool
  default     = false
  description = "Sets FEATURE_LOT_TRACKING on inventory-service (lot tracking / FEFO). See docs/claude/ci-cd.md."
}
variable "email_from" { type = string }
variable "app_base_url" {
  type    = string
  default = ""
}
variable "storage_bucket" { type = string }
variable "storage_bucket_arn" { type = string }
variable "terms_version" { type = string }

variable "alb_security_group_id" { type = string }
variable "gateway_target_group_arn" { type = string }
variable "cors_origins" {
  type    = string
  default = ""
}

variable "frontend_target_group_arn" { type = string }

# CloudFront sets XFF=client, then the ALB appends the CloudFront IP before
# forwarding — so the real client is 2 hops back from the gateway's own
# perspective, not 1.
variable "trusted_proxy_hops" {
  type    = number
  default = 2
}
variable "frontend_sizing" {
  type = object({
    cpu           = number
    memory        = number
    desired_count = number
  })
}

# Secrets Manager ARNs keyed by path under smart/<env>/ (e.g. "jwt/secret"),
# from modules/app-secrets.
variable "secret_arns" { type = map(string) }

# RDS-managed master secret (JSON: username, password). Used only by db-bootstrap.
variable "master_db_secret_arn" { type = string }
variable "db_host" { type = string }
variable "db_name" {
  type    = string
  default = "smart_inventory"
}
variable "runtime_db_role" {
  type    = string
  default = "smart_runtime"
}
