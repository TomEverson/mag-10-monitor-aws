resource "aws_scheduler_schedule" "retrain" {
  name       = "mag10-retrain-schedule"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  # 4:15 PM ET on weekdays — after US market close
  schedule_expression          = "cron(15 16 ? * MON-FRI *)"
  schedule_expression_timezone = "America/New_York"

  target {
    arn      = "arn:aws:scheduler:::aws-sdk:sagemaker:startPipelineExecution"
    role_arn = var.scheduler_role_arn

    input = jsonencode({
      PipelineName                 = "mag10-training-pipeline"
      PipelineExecutionDisplayName = "scheduled-daily"
    })
  }
}
