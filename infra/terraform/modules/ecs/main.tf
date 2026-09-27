variable "env"          { type = string }
variable "vpc_id"       { type = string }
variable "subnet_ids"   { type = list(string) }
variable "services"     { type = list(string) }
variable "account_id"   { type = string }

resource "aws_ecs_cluster" "main" {
  name = "smart-${var.env}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecr_repository" "services" {
  for_each             = toset(var.services)
  name                 = "smart-${each.key}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

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
      Resource = "arn:aws:secretsmanager:us-east-1:${var.account_id}:secret:smart/${var.env}/*"
    }]
  })
}

resource "aws_cloudwatch_log_group" "services" {
  for_each          = toset(var.services)
  name              = "/ecs/smart-${var.env}/${each.key}"
  retention_in_days = var.env == "prod" ? 90 : 30
}

output "cluster_name"             { value = aws_ecs_cluster.main.name }
output "task_execution_role_arn"  { value = aws_iam_role.ecs_task_execution.arn }
