output "repo_uris" {
  value = { for name, repo in aws_ecr_repository.repos : name => repo.repository_url }
}

output "repo_arns" {
  value = [for repo in aws_ecr_repository.repos : repo.arn]
}
