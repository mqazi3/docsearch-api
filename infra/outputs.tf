output "url" {
  value = "https://${aws_route53_record.app.name}"
}

output "public_ip" {
  value = aws_eip.app.public_ip
}

output "instance_id" {
  value = aws_instance.app.id
}

output "deploy_role_arn" {
  value = aws_iam_role.github_deploy.arn
}