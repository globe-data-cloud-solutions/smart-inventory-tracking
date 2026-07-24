terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }
  backend "s3" {}
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

module "cognito" {
  source        = "../../modules/cognito"
  env           = "stage"
  callback_urls = ["https://app.stage.smart-platform.com/auth/callback"]
}

module "s3" {
  source = "../../modules/s3"
  env    = "stage"
}

module "ecs" {
  source     = "../../modules/ecs"
  env        = "stage"
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  account_id = data.aws_caller_identity.current.account_id
  services   = ["api-gateway","auth-service","tenant-service","product-service",
                "inventory-service","order-service","logistics-service",
                "analytics-service","notification-service","sync-service"]
}

module "observability" {
  source     = "../../modules/observability"
  env        = "stage"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}
