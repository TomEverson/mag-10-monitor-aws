output "signal_archive_arn"  { value = aws_lambda_function.signal_archive.arn }
output "s3_to_redshift_arn"  { value = aws_lambda_function.s3_to_redshift.arn }
output "feature_eng_arn"     { value = aws_lambda_function.feature_eng.arn }
output "sqs_queue_url"       { value = aws_sqs_queue.silver_events.url }
output "sqs_queue_arn"       { value = aws_sqs_queue.silver_events.arn }
