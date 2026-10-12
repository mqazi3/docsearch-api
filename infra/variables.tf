variable "region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-2"
}

variable "aws_profile" {
  description = "AWS CLI profile (IAM Identity Center)"
  type        = string
  default     = "docsearch"
}

variable "domain_zone" {
  description = "Existing Route 53 hosted zone"
  type        = string
  default     = "mqazi98.com"
}

variable "subdomain" {
  description = "Subdomain for the API"
  type        = string
  default     = "docsearch"
}

variable "instance_type" {
  description = "EC2 instance type (t4g.small is on a free trial through Dec 31, 2026)"
  type        = string
  default     = "t4g.small"
}

variable "repo_url" {
  description = "Public Git repository the server clones"
  type        = string
  default     = "https://github.com/mqazi3/docsearch-api.git"
}

variable "github_oidc_subject" {
  description = "Exact OIDC subject GitHub sends for pushes to main (uses immutable owner and repo IDs)"
  type        = string
  default     = "repo:mqazi3@160351225/docsearch-api@1412519064:ref:refs/heads/main"
}
