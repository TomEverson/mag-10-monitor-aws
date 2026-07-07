variable "env" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "redshift_sg_id" {
  type = string
}

variable "redshift_db" {
  type = string
}
