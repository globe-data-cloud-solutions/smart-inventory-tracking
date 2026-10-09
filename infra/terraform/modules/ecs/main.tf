resource "aws_ecs_cluster" "main" {
  name = "smart-${var.env}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ECR repositories are created and managed separately to avoid conflicts
# when repositories contain images during destroy. See infra/terraform/docs/ECR_MANAGEMENT.md
# To manually delete ECR repositories:
#   aws ecr delete-repository --repository-name smart-<service> --force --region us-east-1
# resource "aws_ecr_repository" "services" {
#   for_each             = toset(var.enabled_services)
#   name                 = "smart-${each.key}"
#   image_tag_mutability = "MUTABLE"
#
#   image_scanning_configuration {
#     scan_on_push = true
#   }
# }

resource "aws_iam_role" "ecs_task_execution" {
  name = "smart-${var.env}-ecs-task-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets_access" {
  name = "smart-${var.env}-secrets-access"
  role = aws_iam_role.ecs_task_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = "arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:smart/${var.env}/*"
    }]
  })
}

resource "aws_cloudwatch_log_group" "services" {
  for_each          = toset(var.enabled_services)
  name              = "/ecs/smart-${var.env}/${each.key}"
  retention_in_days = var.env == "prod" ? 90 : 30
}

resource "aws_cloudwatch_log_group" "outbox_worker" {
  name              = "/ecs/smart-${var.env}/outbox-worker"
  retention_in_days = var.env == "prod" ? 90 : 30
}

resource "aws_cloudwatch_log_group" "outbox_beat" {
  name              = "/ecs/smart-${var.env}/outbox-beat"
  retention_in_days = var.env == "prod" ? 90 : 30
}

resource "aws_cloudwatch_log_group" "migration" {
  name              = "/ecs/smart-${var.env}/migration"
  retention_in_days = var.env == "prod" ? 90 : 30
}

# Service Connect namespace — every enabled service is a server under this
# namespace with client_alias dns_name = <service name>, so existing
# http://<service>:8000 URLs (gateway env, smoke.sh) keep working unchanged.
resource "aws_service_discovery_http_namespace" "main" {
  name = "smart-${var.env}"
}

resource "aws_security_group" "tasks" {
  name        = "smart-${var.env}-tasks-sg"
  description = "ECS task-to-task traffic for smart-${var.env}, plus ALB ingress to api-gateway"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_vpc_security_group_ingress_rule" "tasks_self" {
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = aws_security_group.tasks.id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}

resource "aws_vpc_security_group_ingress_rule" "tasks_from_alb" {
  security_group_id            = aws_security_group.tasks.id
  referenced_security_group_id = var.alb_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 8000
  to_port                      = 8000
}
