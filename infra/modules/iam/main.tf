data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account = data.aws_caller_identity.current.account_id
  region  = data.aws_region.current.name
}

# ---------------------------------------------------------------------------
# Shared trust policy builders
# ---------------------------------------------------------------------------
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["ec2.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["lambda.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "firehose_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["firehose.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "sagemaker_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["sagemaker.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["ecs-tasks.amazonaws.com"] }
  }
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals { type = "Service"; identifiers = ["scheduler.amazonaws.com"] }
  }
}

# ---------------------------------------------------------------------------
# WebSocket EC2 role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "websocket" {
  name               = "mag10-websocket-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy" "websocket" {
  name = "mag10-websocket-policy"
  role = aws_iam_role.websocket.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["kinesis:PutRecord"]
        Resource = "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-raw-trades"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account}:secret:mag10-finnhub-key*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/mag10/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "websocket" {
  name = "mag10-websocket-instance-profile"
  role = aws_iam_role.websocket.name
}

# ---------------------------------------------------------------------------
# Detection EC2 role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "detection" {
  name               = "mag10-detection-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy" "detection" {
  name = "mag10-detection-policy"
  role = aws_iam_role.detection.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:ListShards",
          "kinesis:SubscribeToShard",
          "kinesis:RegisterStreamConsumer",
          "kinesis:DeregisterStreamConsumer",
          "kinesis:DescribeStreamConsumer",
        ]
        Resource = [
          "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-raw-trades",
          "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-raw-trades/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kinesis:PutRecord"]
        Resource = "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-processed-signals"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}",
          "arn:aws:s3:::${var.s3_bucket_name}/bronze/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:InvokeEndpoint"]
        Resource = "arn:aws:sagemaker:${local.region}:${local.account}:endpoint/mag10-anomaly-endpoint"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account}:secret:mag10-*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/mag10/*"
      },
    ]
  })
}

resource "aws_iam_instance_profile" "detection" {
  name = "mag10-detection-instance-profile"
  role = aws_iam_role.detection.name
}

# ---------------------------------------------------------------------------
# Kinesis Firehose role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "firehose" {
  name               = "mag10-firehose-role"
  assume_role_policy = data.aws_iam_policy_document.firehose_assume.json
}

resource "aws_iam_role_policy" "firehose" {
  name = "mag10-firehose-policy"
  role = aws_iam_role.firehose.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:ListShards",
        ]
        Resource = "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-raw-trades"
      },
      {
        Effect = "Allow"
        Action = ["s3:PutObject", "s3:GetBucketLocation", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}",
          "arn:aws:s3:::${var.s3_bucket_name}/bronze/*",
        ]
      },
      {
        Effect = "Allow"
        Action = ["logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/aws/kinesisfirehose/*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Lambda signal-archive role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_archive" {
  name               = "mag10-lambda-archive-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "lambda_archive" {
  name = "mag10-lambda-archive-policy"
  role = aws_iam_role.lambda_archive.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:ListShards",
          "kinesis:ListStreams",
        ]
        Resource = "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-processed-signals"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject"]
        Resource = "arn:aws:s3:::${var.s3_bucket_name}/silver/*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/aws/lambda/mag10-signal-archive*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Lambda s3-to-redshift role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_redshift" {
  name               = "mag10-lambda-redshift-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "lambda_redshift" {
  name = "mag10-lambda-redshift-policy"
  role = aws_iam_role.lambda_redshift.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
        ]
        Resource = "arn:aws:sqs:${local.region}:${local.account}:mag10-silver-events-queue"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "arn:aws:s3:::${var.s3_bucket_name}/silver/*"
      },
      {
        Effect   = "Allow"
        Action   = ["redshift-serverless:GetCredentials"]
        Resource = "arn:aws:redshift-serverless:${local.region}:${local.account}:workgroup/*"
      },
      {
        Effect = "Allow"
        Action = [
          "redshift-data:ExecuteStatement",
          "redshift-data:DescribeStatement",
          "redshift-data:GetStatementResult",
        ]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account}:secret:mag10-redshift-admin*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/aws/lambda/mag10-s3-to-redshift*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Lambda feature-eng role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "lambda_feature" {
  name               = "mag10-lambda-feature-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "lambda_feature" {
  name = "mag10-lambda-feature-policy"
  role = aws_iam_role.lambda_feature.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kinesis:GetRecords",
          "kinesis:GetShardIterator",
          "kinesis:DescribeStream",
          "kinesis:DescribeStreamSummary",
          "kinesis:ListShards",
          "kinesis:ListStreams",
        ]
        Resource = "arn:aws:kinesis:${local.region}:${local.account}:stream/mag10-raw-trades"
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:PutRecord"]
        Resource = "arn:aws:sagemaker:${local.region}:${local.account}:feature-group/mag10-trade-features"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/aws/lambda/mag10-feature-eng*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# SageMaker execution role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "sagemaker" {
  name               = "mag10-sagemaker-role"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume.json
}

resource "aws_iam_role_policy" "sagemaker" {
  name = "mag10-sagemaker-policy"
  role = aws_iam_role.sagemaker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}",
          "arn:aws:s3:::${var.s3_bucket_name}/*",
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["sagemaker:*"]
        Resource = "arn:aws:sagemaker:${local.region}:${local.account}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchCheckLayerAvailability",
          "ecr:DescribeRepositories",
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/aws/sagemaker/*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# ECS task role (runtime permissions for the container process)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ecs_task" {
  name               = "mag10-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy" "ecs_task" {
  name = "mag10-ecs-task-policy"
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account}:secret:mag10-*"
      },
      {
        Effect = "Allow"
        Action = [
          "sagemaker:DescribeEndpoint",
          "sagemaker:InvokeEndpoint",
        ]
        Resource = "arn:aws:sagemaker:${local.region}:${local.account}:endpoint/mag10-anomaly-endpoint"
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account}:log-group:/mag10/*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# ECS execution role (ECS agent — pulls image, writes logs)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "ecs_execution" {
  name               = "mag10-ecs-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_execution_managed" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "ecs_execution_secrets" {
  name = "mag10-ecs-execution-secrets"
  role = aws_iam_role.ecs_execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = "arn:aws:secretsmanager:${local.region}:${local.account}:secret:mag10-*"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# EventBridge Scheduler role
# ---------------------------------------------------------------------------
resource "aws_iam_role" "scheduler" {
  name               = "mag10-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name = "mag10-scheduler-policy"
  role = aws_iam_role.scheduler.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sagemaker:StartPipelineExecution"]
        Resource = "arn:aws:sagemaker:${local.region}:${local.account}:pipeline/mag10-training-pipeline"
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Redshift Serverless role (for future Redshift-native operations)
# ---------------------------------------------------------------------------
resource "aws_iam_role" "redshift" {
  name               = "mag10-redshift-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "redshift.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "redshift" {
  name = "mag10-redshift-policy"
  role = aws_iam_role.redshift.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          "arn:aws:s3:::${var.s3_bucket_name}",
          "arn:aws:s3:::${var.s3_bucket_name}/*",
        ]
      },
    ]
  })
}
