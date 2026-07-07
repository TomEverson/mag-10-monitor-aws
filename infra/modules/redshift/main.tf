resource "aws_redshiftserverless_namespace" "main" {
  namespace_name      = "mag10-namespace"
  db_name             = var.redshift_db
  admin_username      = "admin"
  manage_admin_password = true
}

resource "aws_redshiftserverless_workgroup" "main" {
  namespace_name = aws_redshiftserverless_namespace.main.namespace_name
  workgroup_name = "mag10-workgroup"
  base_capacity  = 8

  subnet_ids         = var.subnet_ids
  security_group_ids = [var.redshift_sg_id]

  publicly_accessible = false

  depends_on = [aws_redshiftserverless_namespace.main]
}
