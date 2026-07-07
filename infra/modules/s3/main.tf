resource "aws_s3_bucket" "data" {
  bucket        = "mag10-data-${var.env}"
  force_destroy = false
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    id     = "expire-bronze"
    status = "Enabled"
    filter { prefix = "bronze/" }
    expiration { days = 90 }
  }

  rule {
    id     = "expire-silver"
    status = "Enabled"
    filter { prefix = "silver/" }
    expiration { days = 90 }
  }

  rule {
    id     = "expire-features"
    status = "Enabled"
    filter { prefix = "features/" }
    expiration { days = 30 }
  }

  rule {
    id     = "expire-pipeline-logs"
    status = "Enabled"
    filter { prefix = "pipeline-logs/" }
    expiration { days = 30 }
  }
}
