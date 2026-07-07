output "websocket_ec2_id" {
  value = module.ec2.websocket_ec2_id
}

output "detection_ec2_id" {
  value = module.ec2.detection_ec2_id
}

output "kinesis_raw_trades_arn" {
  value = module.kinesis.raw_trades_stream_arn
}

output "kinesis_processed_signals_arn" {
  value = module.kinesis.processed_signals_stream_arn
}

output "s3_bucket_name" {
  value = module.s3.bucket_name
}

output "redshift_endpoint" {
  value = module.redshift.workgroup_endpoint
}

output "redshift_workgroup_name" {
  value = module.redshift.workgroup_name
}

output "dashboard_alb_dns" {
  value = module.ecs.alb_dns_name
}

output "sagemaker_pipeline_arn" {
  value = module.sagemaker.pipeline_arn
}

output "retrain_schedule_arn" {
  value = module.scheduler.schedule_arn
}

output "ecr_repo_uris" {
  value = module.ecr.repo_uris
}
