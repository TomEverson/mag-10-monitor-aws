resource "aws_kinesis_stream" "raw_trades" {
  name             = "mag10-raw-trades"
  shard_count      = 1
  retention_period = 168 # 7 days

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

resource "aws_kinesis_stream" "processed_signals" {
  name             = "mag10-processed-signals"
  shard_count      = 1
  retention_period = 168 # 7 days

  stream_mode_details {
    stream_mode = "PROVISIONED"
  }
}

resource "aws_kinesis_firehose_delivery_stream" "bronze" {
  name        = "mag10-raw-trades-bronze-firehose"
  destination = "extended_s3"

  kinesis_source_configuration {
    kinesis_stream_arn = aws_kinesis_stream.raw_trades.arn
    role_arn           = var.firehose_role_arn
  }

  extended_s3_configuration {
    role_arn           = var.firehose_role_arn
    bucket_arn         = var.s3_bucket_arn
    prefix             = "bronze/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/hour=!{timestamp:HH}/"
    error_output_prefix = "bronze-errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    buffering_size     = 5
    buffering_interval = 60
    compression_format = "GZIP"
  }
}
