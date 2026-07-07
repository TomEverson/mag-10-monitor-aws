# ---------------------------------------------------------------------------
# SQS queues
# ---------------------------------------------------------------------------
resource "aws_sqs_queue" "silver_events_dlq" {
  name                      = "mag10-silver-events-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "silver_events" {
  name                       = "mag10-silver-events-queue"
  visibility_timeout_seconds = 120

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.silver_events_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue_policy" "silver_events" {
  queue_url = aws_sqs_queue.silver_events.url
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.silver_events.arn
      Condition = {
        ArnLike = { "aws:SourceArn" = "arn:aws:s3:::${var.s3_bucket_name}" }
      }
    }]
  })
}

# ---------------------------------------------------------------------------
# S3 event notification → SQS on silver/ prefix
# ---------------------------------------------------------------------------
resource "aws_s3_bucket_notification" "silver" {
  bucket = var.s3_bucket_name
  queue {
    queue_arn     = aws_sqs_queue.silver_events.arn
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "silver/"
  }
  depends_on = [aws_sqs_queue_policy.silver_events]
}

# ---------------------------------------------------------------------------
# Lambda: signal-archive
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "signal_archive" {
  function_name = "mag10-signal-archive"
  role          = var.lambda_archive_role_arn
  package_type  = "Image"
  image_uri     = var.lambda_archive_image
  memory_size   = 256
  timeout       = 60

  environment {
    variables = {
      AWS_REGION_NAME  = var.aws_region
      S3_BUCKET        = var.s3_bucket_name
    }
  }
}

resource "aws_lambda_event_source_mapping" "signal_archive" {
  event_source_arn              = var.kinesis_processed_signals_arn
  function_name                 = aws_lambda_function.signal_archive.arn
  starting_position             = "LATEST"
  batch_size                    = 10
  bisect_batch_on_function_error = true
}

# ---------------------------------------------------------------------------
# Lambda: s3-to-redshift
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "s3_to_redshift" {
  function_name = "mag10-s3-to-redshift"
  role          = var.lambda_redshift_role_arn
  package_type  = "Image"
  image_uri     = var.lambda_redshift_image
  memory_size   = 512
  timeout       = 60

  environment {
    variables = {
      AWS_REGION_NAME         = var.aws_region
      REDSHIFT_WORKGROUP_NAME = var.redshift_workgroup_name
      REDSHIFT_DATABASE       = "mag10"
    }
  }
}

resource "aws_lambda_event_source_mapping" "s3_to_redshift" {
  event_source_arn = aws_sqs_queue.silver_events.arn
  function_name    = aws_lambda_function.s3_to_redshift.arn
  batch_size       = 10
}

# ---------------------------------------------------------------------------
# Lambda: feature-eng
# ---------------------------------------------------------------------------
resource "aws_lambda_function" "feature_eng" {
  function_name = "mag10-feature-eng"
  role          = var.lambda_feature_role_arn
  package_type  = "Image"
  image_uri     = var.lambda_feature_image
  memory_size   = 256
  timeout       = 60

  environment {
    variables = {
      AWS_REGION_NAME         = var.aws_region
      FEATURE_GROUP_NAME      = "mag10-trade-features"
      SAGEMAKER_ENDPOINT_NAME = var.sagemaker_endpoint_name
    }
  }
}

resource "aws_lambda_event_source_mapping" "feature_eng" {
  event_source_arn              = var.kinesis_raw_trades_arn
  function_name                 = aws_lambda_function.feature_eng.arn
  starting_position             = "LATEST"
  batch_size                    = 100
  bisect_batch_on_function_error = true
}
