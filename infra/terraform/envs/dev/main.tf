terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
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

module "ecs" {
  source             = "../../modules/ecs"
  env                = "dev"
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  account_id         = data.aws_caller_identity.current.account_id

  # order/logistics/analytics/notification/sync are stubs — add here to deploy.
  enabled_services = ["api-gateway", "auth-service", "tenant-service", "product-service",
  "inventory-service"]

  service_sizing = {
    default     = { cpu = 256, memory = 512, desired_count = 1, web_concurrency = 1 }
    api-gateway = { cpu = 512, memory = 1024, desired_count = 1, web_concurrency = 2 }
  }
  worker_sizing = { cpu = 256, memory = 512 }
  beat_sizing   = { cpu = 256, memory = 512 }

  email_delivery_mode = "log"
  email_from          = "no-reply@dev.local"
  storage_bucket      = module.s3.bucket_name
  terms_version       = "2026-10"
  app_base_url        = "" # set in I3b
}

module "observability" {
  source     = "../../modules/observability"
  env        = "dev"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}
