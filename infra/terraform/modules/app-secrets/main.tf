# infra/terraform/modules/app-secrets/main.tf
# Application secrets in AWS Secrets Manager, created and populated by Terraform.
# The RDS master password is NOT copied here: only the db-bootstrap ECS task
# receives it. Names follow smart/<env>/<category>/<name> (docs/claude/ci-cd.md §6).

resource "random_password" "jwt" {
  length  = 64
  special = false
}

# Alphanumeric only: embedded in a connection URL and in the bootstrap SQL.
resource "random_password" "runtime_db" {
  length  = 48
  special = false
}

# Dev sample-data passwords (seed_enabled only). Read by the seed ECS task to
# hash the SA account and sample tenant users; nothing else reads them.
# Bump seed_sa_rotation to generate a new SA password. The seed then rotates the
# account only when the deploy runs with rotate_seed_sa=true.
resource "random_password" "seed_sa" {
  count   = var.seed_enabled ? 1 : 0
  length  = 32
  special = false
  keepers = { rotation = var.seed_sa_rotation }
}

resource "random_password" "seed_sample" {
  count   = var.seed_enabled ? 1 : 0
  length  = 32
  special = false
}

locals {
  runtime_db_url = "postgresql+asyncpg://${var.runtime_db_role}:${random_password.runtime_db.result}@%s:5432/${var.db_name}?ssl=require"
  # rediss:// needs ssl_cert_reqs, and the two client libraries spell it
  # differently: redis-py (REDIS_URL, used by the login lockout) takes
  # "required"; Celery (broker and result backend) takes "CERT_REQUIRED".
  # ElastiCache presents a publicly trusted certificate, so verify it.
  redis_url        = "rediss://${var.redis_host}:6379"
  redis_tls_query  = "?ssl_cert_reqs=required"
  celery_tls_query = "?ssl_cert_reqs=CERT_REQUIRED"

  base_secret_values = {
    "db/primary-url"             = format(local.runtime_db_url, var.db_host)
    "db/read-replica-url"        = format(local.runtime_db_url, var.read_db_host)
    "db/app-password"            = random_password.runtime_db.result
    "elasticache/redis-url"      = "${local.redis_url}/0${local.redis_tls_query}"
    "elasticache/celery-broker"  = "${local.redis_url}/0${local.celery_tls_query}"
    "elasticache/celery-backend" = "${local.redis_url}/1${local.celery_tls_query}"
    "jwt/secret"                 = random_password.jwt.result
  }

  seed_secret_values = var.seed_enabled ? {
    "seed/sa-password"     = random_password.seed_sa[0].result
    "seed/sample-password" = random_password.seed_sample[0].result
  } : {}

  secret_values = merge(local.base_secret_values, local.seed_secret_values)
}

resource "aws_secretsmanager_secret" "app" {
  for_each                = toset(keys(local.secret_values))
  name                    = "smart/${var.env}/${each.key}"
  recovery_window_in_days = var.recovery_window_days
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each      = toset(keys(local.secret_values))
  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = local.secret_values[each.key]
}