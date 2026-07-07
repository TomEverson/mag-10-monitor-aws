# Spec: Infrastructure Resources

## Principles

- All AWS resources are defined in Terraform under `infra/`.
- No resources are created manually in the AWS console.
- Naming convention: `mag10-{resource-type}-{env}` where `env` is `prod`.
- Secrets are stored in AWS Secrets Manager; never in Terraform state or
  source code.
- The Terraform state backend is S3 + DynamoDB lock table (defined outside
  this project's Terraform — create manually before first apply).

---

## AWS Account & Region

| Item | Value |
|---|---|
| Region | `us-east-1` |
| Environment | `prod` |

---

## Terraform Module Map

```
infra/
├── main.tf            # Root — calls all modules, wires outputs
├── variables.tf       # Input variables
├── outputs.tf         # Outputs (endpoint URLs, ARNs)
└── modules/
    ├── vpc/           # VPC, subnets, security groups, NAT gateway
    ├── ec2/           # WebSocket EC2 + Detection EC2
    ├── kinesis/       # Kinesis Data Streams + Firehose delivery stream
    ├── s3/            # S3 bucket (bronze + silver + features + models)
    ├── lambda/        # 4 Lambda functions + triggers + SQS
    ├── redshift/      # Redshift Serverless namespace + workgroup
    ├── ecs/           # ECS cluster + Fargate task + ALB (dashboard)
    ├── ecr/           # 3 ECR repositories
    ├── sagemaker/     # Feature Group, Pipeline, Model Registry, Endpoint
    ├── scheduler/     # EventBridge Scheduler for automatic retraining
    └── iam/           # IAM roles and policies for all services
```

---

## VPC (modules/vpc)

| Resource | Value |
|---|---|
| VPC CIDR | `10.0.0.0/16` |
| Public subnets | 2 × `/24` in `us-east-1a`, `us-east-1b` |
| Private subnets | 2 × `/24` in `us-east-1a`, `us-east-1b` |
| NAT Gateway | 1 (in public subnet) |
| Internet Gateway | 1 |

EC2 instances run in private subnets and reach the internet via NAT gateway
(for Finnhub WebSocket and AWS service calls). ECS Fargate and ALB run in
public subnets.

VPC Endpoints (interface): `kinesis-streams`, `s3`, `secretsmanager`,
`redshift-data`, `sagemaker.runtime`, `ecr.api`, `ecr.dkr`, `logs`
(to avoid NAT charges for AWS service traffic).

---

## EC2 Instances (modules/ec2)

Two instances, both t3.micro.

### WebSocket EC2

| Attribute | Value |
|---|---|
| Name | `mag10-websocket-ec2-prod` |
| Instance type | `t3.micro` |
| Subnet | Private subnet (`us-east-1a`) |
| AMI | Amazon Linux 2023 |
| Container | Runs Docker; pulls `mag10-websocket:latest` from ECR |
| IAM role | `mag10-websocket-role` |
| User data | `scripts/ec2-userdata-websocket.sh` |

**IAM role permissions (`mag10-websocket-role`):**
- `kinesis:PutRecord` on `mag10-raw-trades`
- `secretsmanager:GetSecretValue` on `mag10-finnhub-key`
- `ecr:GetAuthorizationToken`, `ecr:BatchGetImage`, `ecr:GetDownloadUrlForLayer`
- `logs:CreateLogStream`, `logs:PutLogEvents`

### Detection EC2

| Attribute | Value |
|---|---|
| Name | `mag10-detection-ec2-prod` |
| Instance type | `t3.micro` |
| Subnet | Private subnet (`us-east-1a`) |
| AMI | Amazon Linux 2023 |
| Container | Runs Docker; pulls `mag10-detection:latest` from ECR |
| IAM role | `mag10-detection-role` |
| User data | `scripts/ec2-userdata-detection.sh` |

**IAM role permissions (`mag10-detection-role`):**
- `kinesis:GetRecords`, `kinesis:GetShardIterator`, `kinesis:DescribeStream`,
  `kinesis:SubscribeToShard`, `kinesis:RegisterStreamConsumer` on `mag10-raw-trades`
- `kinesis:PutRecord` on `mag10-processed-signals`
- `s3:GetObject`, `s3:ListBucket` on `mag10-data-prod/bronze/*` (warm-start)
- `sagemaker:InvokeEndpoint` on `mag10-anomaly-endpoint`
- `secretsmanager:GetSecretValue` on `mag10-sagemaker-endpoint-name`
- `ecr:*` (read-only)
- `logs:CreateLogStream`, `logs:PutLogEvents`

---

## Kinesis (modules/kinesis)

### Data Streams

| Stream | Shards | Retention | Enhanced Fan-Out |
|---|---|---|---|
| `mag10-raw-trades` | 1 | 7 days | Yes (registered consumer for Detection EC2) |
| `mag10-processed-signals` | 1 | 7 days | No |

### Firehose Delivery Stream

| Attribute | Value |
|---|---|
| Name | `mag10-raw-trades-bronze-firehose` |
| Source | Kinesis Data Stream `mag10-raw-trades` |
| Destination | S3 `mag10-data-prod/bronze/` |
| Buffer size | 5 MB |
| Buffer interval | 60 seconds |
| Compression | GZIP |
| IAM role | `mag10-firehose-role` |

---

## S3 (modules/s3)

### Single Bucket, Multiple Prefixes

| Attribute | Value |
|---|---|
| Bucket name | `mag10-data-prod` |
| Region | `us-east-1` |
| Versioning | Disabled |
| Public access | Blocked |
| Encryption | SSE-S3 |

| Prefix | Written by | Contents | Retention |
|---|---|---|---|
| `bronze/` | Kinesis Firehose | Raw validated trades (GZIP NDJSON) | 90 days |
| `silver/` | Lambda `signal-archive` | Detected signals (JSON) | 90 days |
| `features/` | SageMaker Processing Job | Feature matrix (CSV) | 30 days |
| `models/` | SageMaker Training Job | Model artifacts (tar.gz) | Indefinite |
| `evaluations/` | SageMaker Processing Job | Evaluation JSON reports | Indefinite |
| `pipeline-logs/` | SageMaker Pipeline | Execution logs | 30 days |

Lifecycle rules delete Bronze and Silver objects after 90 days, features and
pipeline-logs after 30 days.

---

## Lambda (modules/lambda)

Four functions:

| Function name | Trigger | Memory | Timeout | IAM role |
|---|---|---|---|---|
| `mag10-signal-archive` | Kinesis `mag10-processed-signals` (batch 10) | 256 MB | 60s | `mag10-lambda-archive-role` |
| `mag10-s3-to-redshift` | SQS `mag10-silver-events-queue` | 512 MB | 60s | `mag10-lambda-redshift-role` |
| `mag10-feature-eng` | Kinesis `mag10-raw-trades` (batch 100) | 256 MB | 60s | `mag10-lambda-feature-role` |

All functions are deployed as container images from ECR.

### SQS Queue (silver events)

| Attribute | Value |
|---|---|
| Queue name | `mag10-silver-events-queue` |
| Type | Standard |
| Visibility timeout | 120 seconds |
| Max receive count | 3 (then dead-letter) |
| Dead-letter queue | `mag10-silver-events-dlq` |

S3 event notifications on `silver/` prefix send to this SQS queue, which
triggers Lambda `mag10-s3-to-redshift`.

### IAM Roles

**mag10-lambda-archive-role:**
- `kinesis:GetRecords`, `kinesis:GetShardIterator`, `kinesis:DescribeStream`,
  `kinesis:ListShards` on `mag10-processed-signals`
- `s3:PutObject` on `mag10-data-prod/silver/*`
- `logs:*`

**mag10-lambda-redshift-role:**
- `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes` on `mag10-silver-events-queue`
- `s3:GetObject` on `mag10-data-prod/silver/*`
- `redshift-serverless:GetCredentials` on `mag10-workgroup`
- `redshift-data:ExecuteStatement`, `redshift-data:DescribeStatement`, `redshift-data:GetStatementResult`
- `secretsmanager:GetSecretValue` on Redshift credentials secret
- `logs:*`

**mag10-lambda-feature-role:**
- `kinesis:GetRecords`, `kinesis:GetShardIterator`, `kinesis:DescribeStream` on `mag10-raw-trades`
- `sagemaker:PutRecord` on feature group `mag10-trade-features`
- `logs:*`

---

## Redshift Serverless (modules/redshift)

| Attribute | Value |
|---|---|
| Namespace name | `mag10-namespace` |
| Workgroup name | `mag10-workgroup` |
| Base RPU | 8 |
| Database | `mag10` |
| Admin secret | `mag10-redshift-admin` (Secrets Manager) |
| Subnet IDs | Private subnets |
| Security group | `mag10-redshift-sg` (inbound 5439 from Lambda + Dashboard SGs) |

---

## ECS Fargate (modules/ecs)

| Attribute | Value |
|---|---|
| Cluster name | `mag10-cluster` |
| Service name | `mag10-dashboard-service` |
| Task CPU | 512 |
| Task memory | 1024 MB |
| Image | `mag10-dashboard:latest` from ECR |
| Port | 8080 |
| Desired count | 1 |
| Subnets | Public subnets |
| Security group | `mag10-dashboard-sg` (inbound 8080 from ALB SG) |

### ALB

| Attribute | Value |
|---|---|
| Name | `mag10-dashboard-alb` |
| Type | Application |
| Scheme | Internet-facing |
| Listener | HTTP:80 → Target group (ECS service, port 8080) |
| Health check | `GET /healthz` every 30s |

---

## ECR (modules/ecr)

| Repository name | Image | Built from |
|---|---|---|
| `mag10-websocket` | `mag10-websocket:latest` | `websocket/Dockerfile` |
| `mag10-detection` | `mag10-detection:latest` | `detection/Dockerfile` |
| `mag10-dashboard` | `mag10-dashboard:latest` | `dashboard/Dockerfile` |

Lambda functions also use ECR images:
- `mag10-lambda-archive`
- `mag10-lambda-s3-to-redshift`
- `mag10-lambda-feature-eng`

Image lifecycle policy: keep last 5 tagged images; delete untagged after 1 day.

---

## SageMaker (modules/sagemaker)

| Resource | Name |
|---|---|
| Feature Group | `mag10-trade-features` |
| Pipeline | `mag10-training-pipeline` |
| Model Package Group | `mag10-anomaly-detector` |
| Endpoint Config | `mag10-anomaly-endpoint-config` |
| Endpoint | `mag10-anomaly-endpoint` |
| IAM execution role | `mag10-sagemaker-role` |

**mag10-sagemaker-role permissions:**
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on `mag10-data-prod`
- `sagemaker:*` (scoped to own pipeline, endpoint, feature group)
- `ecr:*` (read-only — for inference container pull)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
- `secretsmanager:GetSecretValue` (pipeline parameters if needed)

---

## EventBridge Scheduler (modules/scheduler)

| Attribute | Value |
|---|---|
| Schedule name | `mag10-retrain-schedule` |
| Cron expression | `cron(15 16 ? * MON-FRI *)` |
| Timezone | `America/New_York` |
| Target | `sagemaker:StartPipelineExecution` on `mag10-training-pipeline` |
| IAM role | `mag10-scheduler-role` |
| Flexible time window | Off |

**mag10-scheduler-role permissions:**
- `sagemaker:StartPipelineExecution` on `mag10-training-pipeline`

---

## Secrets Manager

| Secret name | Consumed by | Description |
|---|---|---|
| `mag10-finnhub-key` | WebSocket EC2 | Finnhub API key |
| `mag10-dashboard-password` | ECS Dashboard | Dashboard login password |
| `mag10-redshift-admin` | Lambda s3-to-redshift, Dashboard | Redshift admin credentials |

Terraform creates the secret resources (empty). Values are added via
`aws secretsmanager put-secret-value` outside of Terraform.

---

## Variables (`infra/variables.tf`)

| Variable | Type | Default | Description |
|---|---|---|---|
| `aws_region` | string | `us-east-1` | AWS region |
| `env` | string | `prod` | Environment suffix |
| `websocket_image` | string | (required) | WebSocket ECR image URI |
| `detection_image` | string | (required) | Detection ECR image URI |
| `dashboard_image` | string | (required) | Dashboard ECR image URI |
| `redshift_db` | string | `mag10` | Redshift database name |
| `sagemaker_endpoint_name` | string | `mag10-anomaly-endpoint` | SageMaker endpoint name |

---

## Outputs (`infra/outputs.tf`)

| Output | Description |
|---|---|
| `websocket_ec2_id` | WebSocket EC2 instance ID |
| `detection_ec2_id` | Detection EC2 instance ID |
| `kinesis_raw_trades_arn` | Kinesis raw-trades stream ARN |
| `kinesis_processed_signals_arn` | Kinesis processed-signals stream ARN |
| `s3_bucket_name` | S3 bucket name |
| `redshift_endpoint` | Redshift Serverless workgroup endpoint |
| `dashboard_alb_dns` | ALB DNS name (dashboard URL) |
| `sagemaker_pipeline_arn` | SageMaker Pipeline ARN |
| `retrain_schedule_arn` | EventBridge Scheduler rule ARN |
| `ecr_repo_uris` | Map of service → ECR repository URI |
