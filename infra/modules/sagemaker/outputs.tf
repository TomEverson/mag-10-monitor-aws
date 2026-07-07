output "feature_group_name"    { value = aws_sagemaker_feature_group.trade_features.feature_group_name }
output "model_package_group"   { value = aws_sagemaker_model_package_group.anomaly_detector.model_package_group_name }
output "pipeline_arn"          { value = "arn:aws:sagemaker:${var.aws_region}:${var.aws_account_id}:pipeline/mag10-training-pipeline" }
