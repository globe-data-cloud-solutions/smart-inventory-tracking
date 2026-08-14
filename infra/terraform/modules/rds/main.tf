variable "env"               { type = string }
variable "vpc_id"            { type = string }
variable "subnet_ids"        { type = list(string) }
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

resource "aws_security_group" "rds" {
  name   = "smart-${var.env}-rds-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}

resource "aws_db_instance" "primary" {
  identifier             = "smart-${var.env}-primary"
  engine                 = "postgres"
  engine_version         = "16.3"
  instance_class         = var.instance_class
  allocated_storage      = var.allocated_storage
  storage_encrypted      = true
  db_name                = "smart_inventory"
  username               = "smart_app"
  manage_master_user_password = true  # stored in Secrets Manager
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  multi_az               = var.env == "prod" ? true : false
  backup_retention_period = var.env == "prod" ? 14 : 7
  skip_final_snapshot    = var.env != "prod"
  deletion_protection    = var.env == "prod"

  parameter_group_name = aws_db_parameter_group.pg16.name
}

resource "aws_db_instance" "read_replica" {
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

output "primary_endpoint" { value = aws_db_instance.primary.endpoint }
output "replica_endpoint"  { value = aws_db_instance.read_replica.endpoint }
