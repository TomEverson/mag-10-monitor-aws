output "workgroup_name"     { value = aws_redshiftserverless_workgroup.main.workgroup_name }
output "workgroup_endpoint" { value = aws_redshiftserverless_workgroup.main.endpoint[0].address }
output "namespace_id"       { value = aws_redshiftserverless_namespace.main.id }
