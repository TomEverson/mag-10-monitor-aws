variable "env" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_id_a" {
  type = string
}

variable "websocket_sg_id" {
  type = string
}

variable "detection_sg_id" {
  type = string
}

variable "websocket_instance_profile_name" {
  type = string
}

variable "detection_instance_profile_name" {
  type = string
}

variable "websocket_image" {
  type = string
}

variable "detection_image" {
  type = string
}

variable "kinesis_raw_trades" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "ecr_registry" {
  type = string
}
