# ---------- Continuous deployment from GitHub Actions ----------
# GitHub proves its identity with a short-lived OIDC token, so no AWS keys are stored
# in GitHub. The role it assumes can do one thing: run the deploy document below on
# this one instance.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Only workflows running on the main branch of this repository.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name                 = "docsearch-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.github_assume.json
  max_session_duration = 3600
}

# A fixed command. CI can trigger a deploy but can't run anything else on the server.
resource "aws_ssm_document" "deploy" {
  name            = "docsearch-deploy"
  document_type   = "Command"
  document_format = "YAML"

  content = <<-DOC
    schemaVersion: "2.2"
    description: Deploy the latest main branch of DocSearch.
    mainSteps:
      - action: aws:runShellScript
        name: deploy
        inputs:
          timeoutSeconds: "900"
          runCommand:
            - export HOME=/root
            - export PATH="$PATH:/snap/bin"
            - bash /opt/docsearch/deploy/deploy.sh main
  DOC
}

data "aws_iam_policy_document" "github_deploy" {
  statement {
    sid       = "RunTheDeployDocumentOnTheAppInstance"
    actions   = ["ssm:SendCommand"]
    resources = [aws_instance.app.arn, aws_ssm_document.deploy.arn]
  }

  statement {
    sid       = "ReadDeployResults"
    actions   = ["ssm:GetCommandInvocation"]
    resources = ["*"] # this action doesn't support resource-level permissions
  }
}

resource "aws_iam_role_policy" "github_deploy" {
  name   = "deploy-only"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy.json
}