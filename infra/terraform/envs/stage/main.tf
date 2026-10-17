terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
  # Static remote state backend. Only `key` differs per environment.
  backend "s3" {
    bucket         = "gdc-smart-terraform-state"
    key            = "smart-inventory-platform/stage/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "smart-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = "us-east-1"
  default_tags {
    tags = {
      Project     = "smart-platform"
      Environment = "stage"
      ManagedBy   = "terraform"
    }
  }
}

module "networking" {
  source   = "../../modules/networking"
  env      = "stage"
  vpc_cidr = "10.20.0.0/16"
}

module "rds" {
  source         = "../../modules/rds"
  env            = "stage"
  vpc_id         = module.networking.vpc_id
  subnet_ids     = module.networking.private_subnet_ids
  instance_class = "db.t4g.large"
}

module "elasticache" {
  source     = "../../modules/elasticache"
  env        = "stage"
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  node_type  = "cache.t4g.medium"
}

module "s3" {
  source = "../../modules/s3"
  env    = "stage"
}

# Lives in TF state — rotate by tainting.
resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

module "alb" {
  source               = "../../modules/alb"
  env                  = "stage"
  vpc_id               = module.networking.vpc_id
  public_subnet_ids    = module.networking.public_subnet_ids
  certificate_arn      = "" # set once ACM cert exists — enables HTTPS + redirect
  origin_verify_secret = random_password.origin_verify.result
}

module "cloudfront" {
  source               = "../../modules/cloudfront"
  env                  = "stage"
  alb_dns_name         = module.alb.alb_dns_name
  origin_verify_secret = random_password.origin_verify.result
  allowed_cidrs        = []
}

module "app_secrets" {
  source               = "../../modules/app-secrets"
  env                  = "stage"
  db_host              = module.rds.primary_address
  read_db_host         = coalesce(module.rds.replica_address, module.rds.primary_address)
  db_name              = "smart_inventory"
  runtime_db_role      = "smart_runtime"
  redis_host           = module.elasticache.primary_address
  recovery_window_days = 30
}

# Inbound DB and Redis access from the ECS tasks. Kept here, not in the
# rds/elasticache modules, so those modules do not depend on ECS.
resource "aws_vpc_security_group_ingress_rule" "rds_from_ecs" {
  security_group_id            = module.rds.security_group_id
  referenced_security_group_id = module.ecs.tasks_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_ecs" {
  security_group_id            = module.elasticache.security_group_id
  referenced_security_group_id = module.ecs.tasks_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
}

module "ecs" {
  source             = "../../modules/ecs"
  env                = "stage"
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  account_id         = data.aws_caller_identity.current.account_id

  # Secrets and the RDS master secret (read only by db-bootstrap).
  secret_arns          = module.app_secrets.arns
  master_db_secret_arn = module.rds.master_secret_arn
  db_host              = module.rds.primary_address

  alb_security_group_id     = module.alb.alb_security_group_id
  gateway_target_group_arn  = module.alb.gateway_target_group_arn
  frontend_target_group_arn = module.alb.frontend_target_group_arn
  cors_origins              = "https://${module.cloudfront.domain_name}"

  # order/logistics/analytics/notification/sync are stubs — add here to deploy.
  enabled_services = ["api-gateway", "auth-service", "tenant-service", "product-service",
  "inventory-service"]

  # All 5 enabled services share the default sizing in stage/prod.
  service_sizing = {
    default = { cpu = 512, memory = 1024, desired_count = 2, web_concurrency = 2 }
  }
  worker_sizing   = { cpu = 256, memory = 512 }
  beat_sizing     = { cpu = 256, memory = 512 }
  frontend_sizing = { cpu = 512, memory = 1024, desired_count = 2 }

  email_delivery_mode  = "ses"
  feature_lot_tracking = true
  email_from           = var.email_from
  storage_bucket       = module.s3.bucket_name
  storage_bucket_arn   = module.s3.bucket_arn
  terms_version        = "2026-10"
  app_base_url         = "https://${module.cloudfront.domain_name}"
}

module "observability" {
  source     = "../../modules/observability"
  env        = "stage"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

output "alb_dns_name" { value = module.alb.alb_dns_name }
output "cloudfront_domain_name" { value = module.cloudfront.domain_name }

# No default — plan must fail until the SES-verified sending domain is decided.
variable "email_from" { type = string }
