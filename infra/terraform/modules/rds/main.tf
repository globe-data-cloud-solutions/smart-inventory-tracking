variable "env" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "allocated_storage" {
  type    = number
  default = 100
}

resource "aws_db_subnet_group" "main" {
  name       = "smart-${var.env}-db-subnet"
  subnet_ids = var.subnet_ids
}

# Inbound 5432 is granted by the environment (aws_vpc_security_group_ingress_rule
# from the ECS tasks SG). Keeping it out of this module avoids an rds <-> ecs
# dependency cycle: ECS needs this module's endpoints for its secrets.
resource "aws_security_group" "rds" {
  name   = "smart-${var.env}-rds-sg"
  vpc_id = var.vpc_id

  # No inline ingress: the 5432 rule is a separate resource in the environment.
  # Do not set ingress here: an explicit list makes this resource own every
  # inbound rule, and an update would revoke the separate rule.
}

resource "aws_db_instance" "primary" {
  identifier                  = "smart-${var.env}-primary"
  engine                      = "postgres"
  engine_version              = "16.3"
  instance_class              = var.instance_class
  allocated_storage           = var.allocated_storage
  storage_encrypted           = true
  db_name                     = "smart_inventory"
  username                    = "smart_app"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.main.name
  vpc_security_group_ids      = [aws_security_group.rds.id]
  multi_az                    = var.env == "prod" ? true : false
  backup_retention_period     = var.env == "prod" ? 14 : 7
  skip_final_snapshot         = var.env != "prod"
  deletion_protection         = var.env == "prod"

  parameter_group_name = aws_db_parameter_group.pg16.name
}

resource "aws_db_instance" "read_replica" {
  count                  = var.env == "prod" ? 1 : 0
  identifier             = "smart-${var.env}-replica"
  replicate_source_db    = aws_db_instance.primary.identifier
  instance_class         = var.instance_class
  vpc_security_group_ids = [aws_security_group.rds.id]
  skip_final_snapshot    = true
}

resource "aws_db_parameter_group" "pg16" {
  name   = "smart-${var.env}-pg16"
  family = "postgres16"

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}

output "primary_address" { value = aws_db_instance.primary.address }
output "replica_address" { value = var.env == "prod" ? aws_db_instance.read_replica[0].address : null }
output "security_group_id" { value = aws_security_group.rds.id }
# RDS-managed master credentials (JSON: username, password). Read only by the
# db-bootstrap ECS task, via ECS secret injection.
output "master_secret_arn" { value = aws_db_instance.primary.master_user_secret[0].secret_arn }
