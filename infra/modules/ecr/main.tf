locals {
  repos = [
    "mag10-websocket",
    "mag10-detection",
    "mag10-dashboard",
    "mag10-lambda-archive",
    "mag10-lambda-s3-to-redshift",
    "mag10-lambda-feature-eng",
  ]
}

resource "aws_ecr_repository" "repos" {
  for_each             = toset(local.repos)
  name                 = each.value
  image_tag_mutability = "MUTABLE"
  force_delete         = false

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "repos" {
  for_each   = aws_ecr_repository.repos
  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Delete untagged images after 1 day"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Keep last 5 tagged images"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v", "latest"]
          countType     = "imageCountMoreThan"
          countNumber   = 5
        }
        action = { type = "expire" }
      },
    ]
  })
}
