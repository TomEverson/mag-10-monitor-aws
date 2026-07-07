variable "env" {
  type = string
}

variable "lambda_archive_image" {
  type = string
}

variable "lambda_redshift_image" {
  type = string
}

variable "lambda_feature_image" {
  type = string
}

variable "lambda_archive_role_arn" {
  type = string
}

variable "lambda_redshift_role_arn" {
  type = string
}

variable "lambda_feature_role_arn" {
  type = string
}

variable "kinesis_processed_signals_arn" {
  type = string
}

variable "kinesis_raw_trades_arn" {
  type = string
}

variable "s3_bucket_name" {
  type = string
}

variable "s3_bucket_arn" {
  type = string
}

variable "redshift_workgroup_name" {
  type = string
}

variable "sagemaker_endpoint_name" {
  type = string
}

variable "aws_region" {
  type = string
}
