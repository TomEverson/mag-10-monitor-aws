#!/usr/bin/env bash
# Full project deploy: build images → push to ECR → terraform apply → schema
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> Authenticating with ECR"
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${ECR_REGISTRY}"

# Build and push all 6 container images
declare -A IMAGES=(
  ["mag10-websocket"]="websocket/Dockerfile"
  ["mag10-detection"]="detection/Dockerfile"
  ["mag10-dashboard"]="dashboard/Dockerfile"
  ["mag10-lambda-archive"]="lambda/signal_archive/Dockerfile"
  ["mag10-lambda-s3-to-redshift"]="lambda/s3_to_redshift/Dockerfile"
  ["mag10-lambda-feature-eng"]="lambda/feature_eng/Dockerfile"
)

for repo in "${!IMAGES[@]}"; do
  dockerfile="${IMAGES[$repo]}"
  uri="${ECR_REGISTRY}/${repo}:latest"
  echo "==> Building ${repo}"
  docker build --platform linux/amd64 -t "${uri}" -f "${dockerfile}" .
  echo "==> Pushing ${repo}"
  docker push "${uri}"
done

# Terraform apply
echo "==> Running terraform apply"
cd infra
terraform init -reconfigure

terraform apply \
  -var="aws_region=${AWS_REGION}" \
  -var="websocket_image=${ECR_REGISTRY}/mag10-websocket:latest" \
  -var="detection_image=${ECR_REGISTRY}/mag10-detection:latest" \
  -var="dashboard_image=${ECR_REGISTRY}/mag10-dashboard:latest" \
  -var="lambda_archive_image=${ECR_REGISTRY}/mag10-lambda-archive:latest" \
  -var="lambda_redshift_image=${ECR_REGISTRY}/mag10-lambda-s3-to-redshift:latest" \
  -var="lambda_feature_image=${ECR_REGISTRY}/mag10-lambda-feature-eng:latest" \
  -auto-approve

WORKGROUP_NAME=$(terraform output -raw redshift_workgroup_name)
cd ..

# Create Redshift schema (idempotent — uses IF NOT EXISTS)
echo "==> Creating Redshift schema"
STMT_ID=$(aws redshift-data execute-statement \
  --workgroup-name "${WORKGROUP_NAME}" \
  --database mag10 \
  --sql "$(cat infra/sql/create_tables.sql)" \
  --query Id --output text)

echo "    Statement ID: ${STMT_ID}"
echo "    Polling for completion..."
for i in $(seq 1 30); do
  STATUS=$(aws redshift-data describe-statement --id "${STMT_ID}" --query Status --output text)
  if [[ "${STATUS}" == "FINISHED" ]]; then
    echo "    Schema created."
    break
  elif [[ "${STATUS}" == "FAILED" ]]; then
    aws redshift-data describe-statement --id "${STMT_ID}" --query Error --output text
    echo "ERROR: Schema creation failed." >&2
    exit 1
  fi
  sleep 3
done

# Populate Secrets Manager if not already set
echo ""
echo "==> Secrets must be populated manually (if not already done):"
echo "    aws secretsmanager put-secret-value --secret-id mag10-finnhub-key      --secret-string '{\"api_key\":\"YOUR_KEY\"}'"
echo "    aws secretsmanager put-secret-value --secret-id mag10-dashboard-password --secret-string '{\"password\":\"YOUR_PASSWORD\"}'"
echo ""
echo "==> Deploy complete."
echo "    Dashboard: http://$(cd infra && terraform output -raw dashboard_alb_dns)"
