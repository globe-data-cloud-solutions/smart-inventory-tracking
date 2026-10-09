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

module "ecs" {
  source             = "../../modules/ecs"
  env                = "stage"
  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids
  account_id         = data.aws_caller_identity.current.account_id

  # order/logistics/analytics/notification/sync are stubs — add here to deploy.
  enabled_services = ["api-gateway", "auth-service", "tenant-service", "product-service",
  "inventory-service"]

  # All 5 enabled services share the default sizing in stage/prod.
  service_sizing = {
    default = { cpu = 512, memory = 1024, desired_count = 2, web_concurrency = 2 }
  }
  worker_sizing = { cpu = 256, memory = 512 }
  beat_sizing   = { cpu = 256, memory = 512 }

  email_delivery_mode = "ses"
  email_from          = var.email_from
  storage_bucket      = module.s3.bucket_name
  terms_version       = "2026-10"
  app_base_url        = "" # set in I3b
}

module "observability" {
  source     = "../../modules/observability"
  env        = "stage"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}

# No default — plan must fail until the SES-verified sending domain is decided.
variable "email_from" { type = string }
