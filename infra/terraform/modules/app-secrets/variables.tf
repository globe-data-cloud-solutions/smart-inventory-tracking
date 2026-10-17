variable "env" { type = string }

variable "db_host" {
  type        = string
  description = "Primary RDS hostname (no port)."
}

variable "read_db_host" {
  type        = string
  description = "Read-replica hostname; the primary's when no replica exists."
}

variable "db_name" { type = string }

variable "runtime_db_role" {
  type        = string
  description = "Non-superuser role the app and migrations connect as (created by db-bootstrap)."
}

variable "redis_host" {
  type        = string
  description = "ElastiCache primary endpoint (TLS on: connect with rediss://)."
}

# 0 lets destroy/reprovision reuse the same names immediately (dev). Stage and
# prod use 30 so an accidental delete can be recovered.
variable "recovery_window_days" {
  type    = number
  default = 30
}

# Dev only: also create the seed passwords (SA account, sample users).
variable "seed_enabled" {
  type    = bool
  default = false
}
