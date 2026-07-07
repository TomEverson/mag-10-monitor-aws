# Feature Group (offline store only — SageMaker Feature Store)
resource "aws_sagemaker_feature_group" "trade_features" {
  feature_group_name             = "mag10-trade-features"
  record_identifier_feature_name = "symbol"
  event_time_feature_name        = "event_time"
  role_arn                       = var.sagemaker_role_arn

  feature_definition { feature_name = "symbol";           feature_type = "String" }
  feature_definition { feature_name = "event_time";       feature_type = "String" }
  feature_definition { feature_name = "batch_trade_count"; feature_type = "Fractional" }
  feature_definition { feature_name = "price_mean";       feature_type = "Fractional" }
  feature_definition { feature_name = "price_std";        feature_type = "Fractional" }
  feature_definition { feature_name = "price_min";        feature_type = "Fractional" }
  feature_definition { feature_name = "price_max";        feature_type = "Fractional" }
  feature_definition { feature_name = "volume_sum";       feature_type = "Fractional" }
  feature_definition { feature_name = "volume_mean";      feature_type = "Fractional" }
  feature_definition { feature_name = "volume_max";       feature_type = "Fractional" }
  feature_definition { feature_name = "price_change_pct"; feature_type = "Fractional" }

  offline_store_config {
    s3_storage_config {
      s3_uri = "s3://${var.s3_bucket_name}/feature-store/"
    }
    disable_glue_table_creation = false
  }
}

# Model Package Group (model versions land here after training pipeline runs)
resource "aws_sagemaker_model_package_group" "anomaly_detector" {
  model_package_group_name        = "mag10-anomaly-detector"
  model_package_group_description = "IsolationForest anomaly scores for MAG-10 trade signals"
}

# NOTE: The SageMaker Endpoint (mag10-anomaly-endpoint) is NOT created here.
# It requires a trained and manually-approved model version in the registry.
# After the first pipeline run and approval, create it with:
#   scripts/create_endpoint.sh
