variable "aws_region" {
  description = "AWS region for the state bucket, lock table, and IAM role."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Short project name used as a prefix for bootstrap resource names. Must match the `project` variable used by the root infra/ module."
  type        = string
  default     = "healthcare-pipeline"
}

variable "github_org" {
  description = "GitHub organization or user that owns the repository (e.g. the 'thealphacubicle' in thealphacubicle/healthcare-aws-data-pipeline)."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
  default     = "healthcare-aws-data-pipeline"
}

variable "create_oidc_provider" {
  description = "Whether to create the GitHub Actions OIDC provider. AWS allows only one provider per URL per account, so set this to false and fill in existing_oidc_provider_arn if one already exists (e.g. from another project)."
  type        = bool
  default     = true
}

variable "existing_oidc_provider_arn" {
  description = "ARN of an existing GitHub Actions OIDC provider. Only used when create_oidc_provider is false."
  type        = string
  default     = ""
}
