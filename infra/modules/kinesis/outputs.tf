output "raw_trades_stream_name"          { value = aws_kinesis_stream.raw_trades.name }
output "raw_trades_stream_arn"           { value = aws_kinesis_stream.raw_trades.arn }
output "processed_signals_stream_name"   { value = aws_kinesis_stream.processed_signals.name }
output "processed_signals_stream_arn"    { value = aws_kinesis_stream.processed_signals.arn }
