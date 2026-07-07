terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # S3 backend + DynamoDB lock table must be created manually before first apply:
  #   aws s3 mb s3://mag10-terraform-state --region us-east-1
  #   aws dynamodb create-table --table-name mag10-terraform-locks \
  #     --attribute-definitions AttributeName=LockID,AttributeType=S \
  #     --key-schema AttributeName=LockID,KeyType=HASH \
  #     --billing-mode PAY_PER_REQUEST --region us-east-1
  backend "s3" {
    bucket         = "mag10-terraform-state"
    key            = "mag10/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "mag10-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

# ---------------------------------------------------------------------------
# Secrets Manager — created empty; populate values with aws secretsmanager
# put-secret-value outside of Terraform
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "finnhub_key" {
  name                    = "mag10-finnhub-key"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "dashboard_password" {
  name                    = "mag10-dashboard-password"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret" "redshift_admin" {
  name                    = "mag10-redshift-admin"
  recovery_window_in_days = 0
}

# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------
module "ecr" {
  source = "./modules/ecr"
  env    = var.env
}

module "s3" {
  source = "./modules/s3"
  env    = var.env
}

module "iam" {
  source         = "./modules/iam"
  env            = var.env
  aws_region     = var.aws_region
  s3_bucket_name = module.s3.bucket_name
}

module "vpc" {
  source     = "./modules/vpc"
  env        = var.env
  aws_region = var.aws_region
}

module "kinesis" {
  source            = "./modules/kinesis"
  env               = var.env
  s3_bucket_arn     = module.s3.bucket_arn
  s3_bucket_name    = module.s3.bucket_name
  firehose_role_arn = module.iam.firehose_role_arn
}

module "ec2" {
  source                          = "./modules/ec2"
  env                             = var.env
  vpc_id                          = module.vpc.vpc_id
  private_subnet_id_a             = module.vpc.private_subnet_ids[0]
  websocket_sg_id                 = module.vpc.websocket_sg_id
  detection_sg_id                 = module.vpc.detection_sg_id
  websocket_instance_profile_name = module.iam.websocket_instance_profile_name
  detection_instance_profile_name = module.iam.detection_instance_profile_name
  websocket_image                 = var.websocket_image
  detection_image                 = var.detection_image
  kinesis_raw_trades              = module.kinesis.raw_trades_stream_name
  aws_region                      = var.aws_region
  ecr_registry                    = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
}

module "lambda" {
  source                          = "./modules/lambda"
  env                             = var.env
  lambda_archive_image            = var.lambda_archive_image
  lambda_redshift_image           = var.lambda_redshift_image
  lambda_feature_image            = var.lambda_feature_image
  lambda_archive_role_arn         = module.iam.lambda_archive_role_arn
  lambda_redshift_role_arn        = module.iam.lambda_redshift_role_arn
  lambda_feature_role_arn         = module.iam.lambda_feature_role_arn
  kinesis_processed_signals_arn   = module.kinesis.processed_signals_stream_arn
  kinesis_raw_trades_arn          = module.kinesis.raw_trades_stream_arn
  s3_bucket_name                  = module.s3.bucket_name
  s3_bucket_arn                   = module.s3.bucket_arn
  redshift_workgroup_name         = "mag10-workgroup"
  sagemaker_endpoint_name         = var.sagemaker_endpoint_name
  aws_region                      = var.aws_region
}

module "redshift" {
  source         = "./modules/redshift"
  env            = var.env
  subnet_ids     = module.vpc.private_subnet_ids
  redshift_sg_id = module.vpc.redshift_sg_id
  redshift_db    = var.redshift_db
}

module "ecs" {
  source                 = "./modules/ecs"
  env                    = var.env
  vpc_id                 = module.vpc.vpc_id
  public_subnet_ids      = module.vpc.public_subnet_ids
  alb_sg_id              = module.vpc.alb_sg_id
  dashboard_sg_id        = module.vpc.dashboard_sg_id
  ecs_task_role_arn      = module.iam.ecs_task_role_arn
  ecs_execution_role_arn = module.iam.ecs_execution_role_arn
  dashboard_image        = var.dashboard_image
  aws_region             = var.aws_region
  aws_account_id         = data.aws_caller_identity.current.account_id
  redshift_secret_arn    = aws_secretsmanager_secret.redshift_admin.arn
  dashboard_secret_arn   = aws_secretsmanager_secret.dashboard_password.arn
}

module "sagemaker" {
  source             = "./modules/sagemaker"
  env                = var.env
  sagemaker_role_arn = module.iam.sagemaker_role_arn
  s3_bucket_name     = module.s3.bucket_name
  aws_region         = var.aws_region
  aws_account_id     = data.aws_caller_identity.current.account_id
}

module "scheduler" {
  source                 = "./modules/scheduler"
  env                    = var.env
  scheduler_role_arn     = module.iam.scheduler_role_arn
  sagemaker_pipeline_arn = module.sagemaker.pipeline_arn
}
