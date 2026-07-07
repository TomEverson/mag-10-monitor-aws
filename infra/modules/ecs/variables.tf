variable "env" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "alb_sg_id" {
  type = string
}

variable "dashboard_sg_id" {
  type = string
}

variable "ecs_task_role_arn" {
  type = string
}

variable "ecs_execution_role_arn" {
  type = string
}

variable "dashboard_image" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "redshift_secret_arn" {
  type = string
}

variable "dashboard_secret_arn" {
  type = string
}
