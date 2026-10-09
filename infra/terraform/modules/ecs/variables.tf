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
