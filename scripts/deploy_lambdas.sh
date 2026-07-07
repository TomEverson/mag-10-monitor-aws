#!/usr/bin/env bash
# Quick redeploy of Lambda container images only (no terraform apply)
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ECR_REGISTRY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> Authenticating with ECR"
aws ecr get-login-password --region "${AWS_REGION}" | \
  docker login --username AWS --password-stdin "${ECR_REGISTRY}"

declare -A LAMBDA_IMAGES=(
  ["mag10-signal-archive"]="mag10-lambda-archive:lambda/signal_archive/Dockerfile"
  ["mag10-s3-to-redshift"]="mag10-lambda-s3-to-redshift:lambda/s3_to_redshift/Dockerfile"
  ["mag10-feature-eng"]="mag10-lambda-feature-eng:lambda/feature_eng/Dockerfile"
)

for func in "${!LAMBDA_IMAGES[@]}"; do
  IFS=':' read -r repo dockerfile <<< "${LAMBDA_IMAGES[$func]}"
  uri="${ECR_REGISTRY}/${repo}:latest"
  echo "==> Building ${repo}"
  docker build --platform linux/amd64 -t "${uri}" -f "${dockerfile}" .
  echo "==> Pushing ${repo}"
  docker push "${uri}"
  echo "==> Updating Lambda ${func}"
  aws lambda update-function-code \
    --function-name "${func}" \
    --image-uri "${uri}" \
    --region "${AWS_REGION}" \
    --output text --query 'FunctionArn'
done

echo "==> Lambda redeploy complete."
