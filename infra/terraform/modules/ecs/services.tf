locals {
  secret_arn_prefix = "arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:smart/${var.env}"

  common_secrets = [
    { name = "DATABASE_URL", valueFrom = "${local.secret_arn_prefix}/db/primary-url" },
    { name = "DATABASE_READ_URL", valueFrom = "${local.secret_arn_prefix}/db/read-replica-url" },
    { name = "REDIS_URL", valueFrom = "${local.secret_arn_prefix}/elasticache/redis-url" },
    { name = "CELERY_BROKER_URL", valueFrom = "${local.secret_arn_prefix}/elasticache/celery-broker" },
    { name = "CELERY_RESULT_BACKEND", valueFrom = "${local.secret_arn_prefix}/elasticache/celery-backend" },
    { name = "JWT_SECRET", valueFrom = "${local.secret_arn_prefix}/jwt/secret" },
  ]

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
        { TRUSTED_PROXY_HOPS = "1" },
        local.gateway_service_urls
      ) : { TRUST_PROXY_HEADERS = "true" }
    )
  }
}

resource "aws_ecs_task_definition" "services" {
  for_each                 = toset(var.enabled_services)
  family                   = "smart-${var.env}-${each.key}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = tostring(local.service_sizing_resolved[each.key].cpu)
  memory                   = tostring(local.service_sizing_resolved[each.key].memory)
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  # task_role_arn (runtime AWS perms — S3, SES): scoped in I3b/I3c, not this PR.

  container_definitions = jsonencode([
    {
      name      = each.key
      image     = "${var.account_id}.dkr.ecr.${var.region}.amazonaws.com/smart-${each.key}:${var.env}-latest"
      essential = true
      portMappings = [
        { name = "http", containerPort = 8000, protocol = "tcp" }
      ]
      environment = [for k, v in local.service_env[each.key] : { name = k, value = v }]
      secrets     = local.common_secrets
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
      secrets     = local.common_secrets
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
      secrets     = local.common_secrets
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
