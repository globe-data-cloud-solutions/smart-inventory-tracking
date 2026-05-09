terraform {
  workspace = "dev"
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

module "cognito" {
  source         = "../../modules/cognito"
  env            = "dev"
  callback_urls  = ["https://app.dev.smart-platform.com/auth/callback"]
}

module "s3" {
  source = "../../modules/s3"
  env    = "dev"
}

module "ecs" {
  source     = "../../modules/ecs"
  env        = "dev"
  vpc_id     = module.networking.vpc_id
  subnet_ids = module.networking.private_subnet_ids
  account_id = data.aws_caller_identity.current.account_id
  services   = ["api-gateway","auth-service","tenant-service","product-service",
                "inventory-service","order-service","logistics-service",
                "analytics-service","notification-service","sync-service"]
}

module "observability" {
  source     = "../../modules/observability"
  env        = "dev"
  account_id = data.aws_caller_identity.current.account_id
}

data "aws_caller_identity" "current" {}
