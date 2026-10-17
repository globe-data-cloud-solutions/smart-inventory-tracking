# Secrets are created by modules/app-secrets. ECS must get the full secret ARN:
# a bare name such as "smart/dev/jwt/secret" is read as an SSM Parameter Store
# name, which the execution role cannot read.
locals {
  common_secrets = [
    { name = "DATABASE_URL", key = "db/primary-url" },
    { name = "DATABASE_READ_URL", key = "db/read-replica-url" },
    { name = "REDIS_URL", key = "elasticache/redis-url" },
    { name = "CELERY_BROKER_URL", key = "elasticache/celery-broker" },
    { name = "CELERY_RESULT_BACKEND", key = "elasticache/celery-backend" },
    { name = "JWT_SECRET", key = "jwt/secret" },
  ]

  # Shape ECS expects in container definitions: { name, valueFrom = <ARN> }.
  secret_refs = [for s in local.common_secrets : { name = s.name, valueFrom = var.secret_arns[s.key] }]

  common_env = {
    ENVIRONMENT         = var.env
    JWT_ALGORITHM       = "HS256"
    JWT_EXPIRE_MINUTES  = "60"
    AWS_REGION          = var.region
    TERMS_VERSION       = var.terms_version
    EMAIL_DELIVERY_MODE = var.email_delivery_mode
    EMAIL_FROM          = var.email_from
    APP_BASE_URL        = var.app_base_url
    STORAGE_BACKEND     = "s3"
    STORAGE_S3_BUCKET   = var.storage_bucket
  }

  # *_SERVICE_URL for whichever services are actually deployed in this env —
  # same keys as scripts/docker/smoke.sh (e.g. "auth-service" -> AUTH_SERVICE_URL).
  gateway_service_urls = {
    for svc in var.enabled_services :
    "${upper(replace(svc, "-", "_"))}_URL" => "http://${svc}:8000"
    if svc != "api-gateway"
  }

  service_sizing_resolved = {
    for svc in var.enabled_services :
    svc => lookup(var.service_sizing, svc, var.service_sizing["default"])
  }

  service_env = {
    for svc in var.enabled_services :
    svc => merge(
      local.common_env,
      { WEB_CONCURRENCY = tostring(local.service_sizing_resolved[svc].web_concurrency) },
      svc == "api-gateway" ? merge(
        { TRUSTED_PROXY_HOPS = tostring(var.trusted_proxy_hops) },
        local.gateway_service_urls,
        # Gateway falls back to its own local default when unset.
        var.cors_origins != "" ? { CORS_ORIGINS = var.cors_origins } : {}
      ) : { TRUST_PROXY_HEADERS = "true" },
      svc == "inventory-service" ? { FEATURE_LOT_TRACKING = var.feature_lot_tracking ? "true" : "false" } : {}
    )
  }

  # task_role_arn per service — only where a role exists (product-service: S3
  # uploads; auth/tenant-service: SES send). Everything else gets none.
  service_task_role_arns = merge(
    { "product-service" = aws_iam_role.product_service_task.arn },
    { for svc, role in aws_iam_role.ses_senders : svc => role.arn }
  )
}

resource "aws_ecs_task_definition" "services" {
  for_each                 = toset(var.enabled_services)
  family                   = "smart-${var.env}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(local.service_sizing_resolved[each.key].cpu)
  memory                   = tostring(local.service_sizing_resolved[each.key].memory)
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = lookup(local.service_task_role_arns, each.key, null)

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-${each.key}:${var.env}-latest"
      essential = true
      portMappings = [
        { name = "http", containerPort = 8000, protocol = "tcp" }
      ]
      environment = [for k, v in local.service_env[each.key] : { name = k, value = v }]
      secrets     = local.secret_refs
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.services[each.key].name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = each.key
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"]
        interval    = 30
        retries     = 3
        startPeriod = 30
        timeout     = 5
      }
    }
  ])
}

resource "aws_ecs_service" "services" {
  for_each        = toset(var.enabled_services)
  name            = "smart-${var.env}-${each.key}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.services[each.key].arn
  desired_count   = local.service_sizing_resolved[each.key].desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  dynamic "load_balancer" {
    for_each = each.key == "api-gateway" ? [1] : []
    content {
      target_group_arn = var.gateway_target_group_arn
      container_name   = "api-gateway"
      container_port   = 8000
    }
  }

  health_check_grace_period_seconds = each.key == "api-gateway" ? 60 : null

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn

    service {
      port_name      = "http"
      discovery_name = each.key
      client_alias {
        port     = 8000
        dns_name = each.key
      }
    }
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ── Frontend (standalone Next.js) ──────────────────────────────────────────
# Always deployed — not part of enabled_services. NEXT_PUBLIC_API_URL is
# baked into the image at build time; no backend secrets or task role.

resource "aws_ecs_task_definition" "frontend" {
  family                   = "smart-${var.env}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.frontend_sizing.cpu)
  memory                   = tostring(var.frontend_sizing.memory)
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "frontend"
      image     = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-frontend:${var.env}-latest"
      essential = true
      portMappings = [
        { name = "http", containerPort = 3000, protocol = "tcp" }
      ]
      environment = [
        { name = "NODE_ENV", value = "production" },
        { name = "PORT", value = "3000" },
        { name = "HOSTNAME", value = "0.0.0.0" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "frontend"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "node -e \"fetch('http://localhost:3000/').then(r=>process.exit(r.status<500?0:1)).catch(()=>process.exit(1))\""]
        interval    = 30
        retries     = 3
        startPeriod = 30
        timeout     = 5
      }
    }
  ])
}

resource "aws_ecs_service" "frontend" {
  name            = "smart-${var.env}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_sizing.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = var.frontend_target_group_arn
    container_name   = "frontend"
    container_port   = 3000
  }

  health_check_grace_period_seconds = 60

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# ── DB bootstrap task (runtime role) ──────────────────────────────────────
# One-off, run by the deploy workflow BEFORE migrations. Creates or updates the
# runtime DB role (smart_runtime) that the app and migrations connect as.
# The RDS master credentials are injected by ECS from the RDS-managed secret;
# they are never written to state, logs, or any other secret. Idempotent.

resource "aws_ecs_task_definition" "db_bootstrap" {
  family                   = "smart-${var.env}-db-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "db-bootstrap"
      image     = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-migration:${var.env}-latest"
      essential = true
      command   = ["python", "/app/backend/migrations/bootstrap_db_role.py"]
      environment = [
        { name = "ENVIRONMENT", value = var.env },
        { name = "PGHOST", value = var.db_host },
        { name = "PGPORT", value = "5432" },
        { name = "PGDATABASE", value = var.db_name },
        { name = "RUNTIME_DB_ROLE", value = var.runtime_db_role },
      ]
      secrets = [
        { name = "PGUSER", valueFrom = "${var.master_db_secret_arn}:username::" },
        { name = "PGPASSWORD", valueFrom = "${var.master_db_secret_arn}:password::" },
        { name = "RUNTIME_DB_PASSWORD", valueFrom = var.secret_arns["db/app-password"] },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.migration.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "db-bootstrap"
        }
      }
    }
  ])
}

# ── Migration task (alembic upgrade head + permission seed) ───────────────
# No aws_ecs_service — run on demand via `aws ecs run-task` from the deploy
# workflow, after db-bootstrap and before any service rollout.

resource "aws_ecs_task_definition" "migration" {
  family                   = "smart-${var.env}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name      = "migration"
      image     = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-migration:${var.env}-latest"
      essential = true
      environment = [
        { name = "ENVIRONMENT", value = var.env }
      ]
      secrets = [
        for s in local.secret_refs : s
        if contains(["DATABASE_URL", "DATABASE_READ_URL"], s.name)
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.migration.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "migration"
        }
      }
    }
  ])
}

# ── Outbox worker + beat (shared.outbox.worker Celery app) ────────────────
# Both run the tenant-service image (matches scripts/docker/smoke.sh); the
# image ENTRYPOINT still runs the env_guard pre-flight before celery starts.

resource "aws_ecs_task_definition" "outbox_worker" {
  family                   = "smart-${var.env}-outbox-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.worker_sizing.cpu)
  memory                   = tostring(var.worker_sizing.memory)
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name        = "outbox-worker"
      image       = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-tenant-service:${var.env}-latest"
      essential   = true
      command     = ["celery", "-A", "shared.outbox.worker", "worker", "--loglevel=info"]
      environment = [for k, v in local.common_env : { name = k, value = v }]
      secrets     = local.secret_refs
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.outbox_worker.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "outbox-worker"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "outbox_worker" {
  name            = "smart-${var.env}-outbox-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.outbox_worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # Client-only Service Connect — the worker calls other services, nothing calls it.
  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

resource "aws_ecs_task_definition" "outbox_beat" {
  family                   = "smart-${var.env}-outbox-beat"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(var.beat_sizing.cpu)
  memory                   = tostring(var.beat_sizing.memory)
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn

  container_definitions = jsonencode([
    {
      name        = "outbox-beat"
      image       = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-tenant-service:${var.env}-latest"
      essential   = true
      command     = ["celery", "-A", "shared.outbox.worker", "beat", "--loglevel=info"]
      environment = [for k, v in local.common_env : { name = k, value = v }]
      secrets     = local.secret_refs
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.outbox_beat.name
          "awslogs-region"        = var.region
          "awslogs-stream-prefix" = "outbox-beat"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "outbox_beat" {
  name            = "smart-${var.env}-outbox-beat"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.outbox_beat.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  # Never two beat schedulers running at once — a deploy must drain the old
  # beat before the new one starts, not run both side by side.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.tasks.id]
    assign_public_ip = false
  }

  service_connect_configuration {
    enabled   = true
    namespace = aws_service_discovery_http_namespace.main.arn
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}
