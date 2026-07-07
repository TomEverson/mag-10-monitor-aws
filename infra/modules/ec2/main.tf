data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "websocket" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  subnet_id              = var.private_subnet_id_a
  vpc_security_group_ids = [var.websocket_sg_id]
  iam_instance_profile   = var.websocket_instance_profile_name

  user_data = base64encode(templatefile("${path.module}/../../scripts/ec2-userdata-websocket.sh", {
    aws_region         = var.aws_region
    ecr_registry       = var.ecr_registry
    websocket_image    = var.websocket_image
    kinesis_raw_trades = var.kinesis_raw_trades
  }))

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "mag10-websocket-ec2-${var.env}" }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_instance" "detection" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = "t3.micro"
  subnet_id              = var.private_subnet_id_a
  vpc_security_group_ids = [var.detection_sg_id]
  iam_instance_profile   = var.detection_instance_profile_name

  user_data = base64encode(templatefile("${path.module}/../../scripts/ec2-userdata-detection.sh", {
    aws_region         = var.aws_region
    ecr_registry       = var.ecr_registry
    detection_image    = var.detection_image
    kinesis_raw_trades = var.kinesis_raw_trades
  }))

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
    encrypted   = true
  }

  tags = { Name = "mag10-detection-ec2-${var.env}" }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}
