output "vpc_id"              { value = aws_vpc.main.id }
output "public_subnet_ids"   { value = [aws_subnet.public_a.id, aws_subnet.public_b.id] }
output "private_subnet_ids"  { value = [aws_subnet.private_a.id, aws_subnet.private_b.id] }
output "websocket_sg_id"     { value = aws_security_group.websocket.id }
output "detection_sg_id"     { value = aws_security_group.detection.id }
output "alb_sg_id"           { value = aws_security_group.alb.id }
output "dashboard_sg_id"     { value = aws_security_group.dashboard.id }
output "redshift_sg_id"      { value = aws_security_group.redshift.id }
