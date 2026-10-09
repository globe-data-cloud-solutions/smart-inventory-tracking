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
  source                     = "../../modules/rds"
  env                        = "dev"
  vpc_id                     = module.networking.vpc_id
  subnet_ids                 = module.networking.private_subnet_ids
  instance_class             = "db.t4g.medium"
  allowed_security_group_ids = [module.ecs.tasks_security_group_id]
}

module "elasticache" {
  source                     = "../../modules/elasticache"
  env                        = "dev"
  vpc_id                     = module.networking.vpc_id
  subnet_ids                 = module.networking.private_subnet_ids
  node_type                  = "cache.t4g.small"
  allowed_security_group_ids = [module.ecs.tasks_security_group_id]
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
}

module "ecs" {
  source             = "../../modules/ecs"
  env                = "dev"
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  account_id         = data.aws_caller_identity.current.account_id

  alb_security_group_id     = module.alb.alb_security_group_id
  gateway_target_group_arn  = module.alb.gateway_target_group_arn
  frontend_target_group_arn = module.alb.frontend_target_group_arn
  cors_origins              = "https://${module.cloudfront.domain_name}"

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

  email_delivery_mode = "log"
  email_from          = "no-reply@dev.local"
  storage_bucket      = module.s3.bucket_name
  storage_bucket_arn  = module.s3.bucket_arn
  terms_version       = "2026-10"
  app_base_url        = "https://${module.cloudfront.domain_name}"
}

module "observability" {
  source     = "../../modules/observability"
  env        = "dev"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

output "alb_dns_name" { value = module.alb.alb_dns_name }
output "cloudfront_domain_name" { value = module.cloudfront.domain_name }

# No default — dev fails closed; set via TF_VAR_allowed_cidrs from the
# GitHub repo variable DEV_ALLOWED_CIDRS.
variable "allowed_cidrs" { type = list(string) }
