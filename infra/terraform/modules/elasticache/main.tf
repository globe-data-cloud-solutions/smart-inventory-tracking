variable "env"        { type = string }
variable "vpc_id"    { type = string }
variable "subnet_ids" { type = list(string) }
variable "node_type" {
  type    = string
  default = "cache.t4g.small"
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "smart-${var.env}-redis"
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "redis" {
  name   = "smart-${var.env}-redis-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "smart-${var.env}-redis"
  description          = "SMART ${var.env} — Celery broker + session cache"
  node_type            = var.node_type
  num_cache_clusters   = var.env == "prod" ? 2 : 1
  port                 = 6379
  subnet_group_name    = aws_elasticache_subnet_group.main.name
  security_group_ids   = [aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  automatic_failover_enabled = var.env == "prod" ? true : false
}

output "primary_endpoint" {
  value = aws_elasticache_replication_group.main.primary_endpoint_address
}
