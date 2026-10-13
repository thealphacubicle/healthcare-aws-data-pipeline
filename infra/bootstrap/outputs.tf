output "tf_state_bucket" {
  description = "S3 bucket for the root module's Terraform state. Pass as `bucket` in backend.hcl."
  value       = aws_s3_bucket.tf_state.id
}

output "tf_lock_table" {
  description = "DynamoDB table for Terraform state locking. Pass as `dynamodb_table` in backend.hcl."
  value       = aws_dynamodb_table.tf_lock.name
}

output "github_deploy_role_arn" {
  description = "IAM role ARN for GitHub Actions to assume via OIDC. Store as the AWS_DEPLOY_ROLE_ARN repo secret."
  value       = aws_iam_role.deploy.arn
}
