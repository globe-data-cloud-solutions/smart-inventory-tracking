output "cluster_name" { value = aws_ecs_cluster.main.name }
output "task_execution_role_arn" { value = aws_iam_role.ecs_task_execution.arn }
output "tasks_security_group_id" { value = aws_security_group.tasks.id }
output "service_names" { value = [for svc in var.enabled_services : aws_ecs_service.services[svc].name] }
output "namespace_arn" { value = aws_service_discovery_http_namespace.main.arn }
output "migration_task_family" { value = aws_ecs_task_definition.migration.family }
output "product_service_task_role_arn" { value = aws_iam_role.product_service_task.arn }
output "ses_sender_task_role_arns" { value = { for svc, role in aws_iam_role.ses_senders : svc => role.arn } }
