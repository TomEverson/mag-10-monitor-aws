variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "env" {
  type    = string
  default = "prod"
}

variable "redshift_db" {
  type    = string
  default = "mag10"
}

variable "sagemaker_endpoint_name" {
  type    = string
  default = "mag10-anomaly-endpoint"
}

# Container image URIs — set by deploy.sh at apply time
variable "websocket_image" {
  type        = string
  description = "WebSocket ECR image URI (e.g. 123456789.dkr.ecr.us-east-1.amazonaws.com/mag10-websocket:latest)"
}

variable "detection_image" {
  type        = string
  description = "Detection ECR image URI"
}

variable "dashboard_image" {
  type        = string
  description = "Dashboard ECR image URI"
}

variable "lambda_archive_image" {
  type        = string
  description = "Lambda signal-archive ECR image URI"
}

variable "lambda_redshift_image" {
  type        = string
  description = "Lambda s3-to-redshift ECR image URI"
}

variable "lambda_feature_image" {
  type        = string
  description = "Lambda feature-eng ECR image URI"
}
