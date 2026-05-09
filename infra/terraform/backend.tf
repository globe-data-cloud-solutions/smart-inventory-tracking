terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.50"
    }
  }

  # Remote state: S3 + DynamoDB locking
  backend "s3" {
    bucket         = "smart-terraform-state"
    key            = "smart-platform/${terraform.workspace}/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "smart-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "smart-platform"
      Environment = terraform.workspace
      ManagedBy   = "terraform"
    }
  }
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}
