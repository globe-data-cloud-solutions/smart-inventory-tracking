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
    key            = "smart-inventory-platform/dev/terraform.tfstate"
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
      Environment = "dev"
      ManagedBy   = "terraform"
    }
  }
}

module "networking" {
  source   = "../../modules/networking"
  env      = "dev"
  vpc_cidr = "10.10.0.0/16"
}

module "rds" {
  source         = "../../modules/rds"
  env            = "dev"
  vpc_id         = module.networking.vpc_id
  subnet_ids     = module.networking.private_subnet_ids
  instance_class = "db.t4g.medium"
}

module "elasticache" {
  source     = "../../modules/elasticache"
  env        = "dev"
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  node_type  = "cache.t4g.small"
}

module "s3" {
  source = "../../modules/s3"
  env    = "dev"
}

# Lives in TF state — rotate by tainting.
resource "random_password" "origin_verify" {
  length  = 48
  special = false
}

# Public name for the app. Must be a subdomain of a hosted zone in this account.
locals {
  app_domain = "smart.hplink.io"
  app_zone   = "hplink.io"
}

module "custom_domain" {
  source      = "../../modules/custom-domain"
  domain_name = local.app_domain
  zone_name   = local.app_zone
}

module "alb" {
  source               = "../../modules/alb"
  env                  = "dev"
  vpc_id               = module.networking.vpc_id
  public_subnet_ids    = module.networking.public_subnet_ids
  certificate_arn      = "" # set once ACM cert exists — enables HTTPS + redirect
  origin_verify_secret = random_password.origin_verify.result
}

module "cloudfront" {
  source               = "../../modules/cloudfront"
  env                  = "dev"
  alb_dns_name         = module.alb.alb_dns_name
  origin_verify_secret = random_password.origin_verify.result
  allowed_cidrs        = var.allowed_cidrs # dev fails closed — set via TF_VAR_allowed_cidrs
  aliases              = [local.app_domain]
  acm_certificate_arn  = module.custom_domain.certificate_arn
  route53_zone_id      = module.custom_domain.zone_id
}

module "app_secrets" {
  source               = "../../modules/app-secrets"
  env                  = "dev"
  db_host              = module.rds.primary_address
  read_db_host         = coalesce(module.rds.replica_address, module.rds.primary_address)
  db_name              = "smart_inventory"
  runtime_db_role      = "smart_runtime"
  redis_host           = module.elasticache.primary_address
  recovery_window_days = 0
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
  env                = "dev"
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
  # The custom domain is the browser origin; the CloudFront name stays allowed
  # because the frontend image bakes NEXT_PUBLIC_API_URL to it (deploy.yml).
  cors_origins = "https://${local.app_domain},https://${module.cloudfront.domain_name}"

  # order/logistics/analytics/notification/sync are stubs — add here to deploy.
  enabled_services = ["api-gateway", "auth-service", "tenant-service", "product-service",
  "inventory-service"]

  service_sizing = {
    default     = { cpu = 256, memory = 512, desired_count = 1, web_concurrency = 1 }
    api-gateway = { cpu = 512, memory = 1024, desired_count = 1, web_concurrency = 2 }
  }
  worker_sizing   = { cpu = 256, memory = 512 }
  beat_sizing     = { cpu = 256, memory = 512 }
  frontend_sizing = { cpu = 256, memory = 512, desired_count = 1 }

  email_delivery_mode  = "log"
  feature_lot_tracking = true
  email_from           = "no-reply@dev.local"
  storage_bucket       = module.s3.bucket_name
  storage_bucket_arn   = module.s3.bucket_arn
  terms_version        = "2026-10"
  app_base_url         = "https://${local.app_domain}"
}

module "observability" {
  source     = "../../modules/observability"
  env        = "dev"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

output "alb_dns_name" { value = module.alb.alb_dns_name }
output "cloudfront_domain_name" { value = module.cloudfront.domain_name }
output "app_domain_name" { value = local.app_domain }

# No default — dev fails closed; set via TF_VAR_allowed_cidrs from the
# GitHub repo variable DEV_ALLOWED_CIDRS.
variable "allowed_cidrs" { type = list(string) }
