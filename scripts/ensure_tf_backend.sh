#!/usr/bin/env bash
# Create (if needed) the S3 bucket used for Terraform remote state. The name
# defaults to an account-scoped value so it is unique without hardcoding an
# account ID in the repo.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${TF_STATE_BUCKET:-healthcare-pipeline-tfstate-${ACCOUNT_ID}}"
KEY="${TF_STATE_KEY:-healthcare-pipeline/terraform.tfstate}"

if aws s3api head-bucket --bucket "${BUCKET}" --region "${REGION}"; then
  echo "Using existing Terraform state bucket ${BUCKET}"
else
  echo "Creating Terraform state bucket ${BUCKET} in ${REGION}"
  if [ "${REGION}" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}"
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
  aws s3api put-public-access-block --bucket "${BUCKET}" --region "${REGION}" \
    --public-access-block-configuration \
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
  aws s3api put-bucket-versioning --bucket "${BUCKET}" --region "${REGION}" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "${BUCKET}" --region "${REGION}" \
    --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
fi

if [ -n "${GITHUB_ENV:-}" ]; then
  {
    echo "AWS_REGION=${REGION}"
    echo "TF_STATE_BUCKET=${BUCKET}"
    echo "TF_STATE_KEY=${KEY}"
  } >> "${GITHUB_ENV}"
fi

echo "Terraform backend ready: s3://${BUCKET}/${KEY}"
