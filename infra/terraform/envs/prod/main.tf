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
    bucket         = "smart-terraform-state"
    key            = "smart-platform/prod/terraform.tfstate"
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
      Environment = "prod"
      ManagedBy   = "terraform"
    }
  }
}

module "networking" {
  source   = "../../modules/networking"
  env      = "prod"
  vpc_cidr = "10.30.0.0/16"
}

module "rds" {
  source            = "../../modules/rds"
  env               = "prod"
  vpc_id            = module.networking.vpc_id
  subnet_ids        = module.networking.private_subnet_ids
  instance_class    = "db.r8g.large"
  allocated_storage = 500
}

module "elasticache" {
  source     = "../../modules/elasticache"
  env        = "prod"
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  node_type  = "cache.r7g.large"
}

module "cognito" {
  source        = "../../modules/cognito"
  env           = "prod"
  callback_urls = ["https://app.smart-platform.com/auth/callback"]
}

module "s3" {
  source = "../../modules/s3"
  env    = "prod"
}

module "ecs" {
  source     = "../../modules/ecs"
  env        = "prod"
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  account_id = data.aws_caller_identity.current.account_id
  services   = ["api-gateway","auth-service","tenant-service","product-service",
                "inventory-service","order-service","logistics-service",
                "analytics-service","notification-service","sync-service"]
}

module "observability" {
  source     = "../../modules/observability"
  env        = "prod"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}
