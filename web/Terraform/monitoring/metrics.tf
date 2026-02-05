# Filter for S3 GetObject events in CloudTrail logs
# This resource creates a CloudWatch log metric filter that counts the number of GetObject events in the CloudTrail logs.
# The filter is applied to the CloudWatch log group created
resource "aws_cloudwatch_log_metric_filter" "s3_get_filter" {
  name           = "CountS3GetObject"
  log_group_name = aws_cloudwatch_log_group.trail_logs.name

  pattern = "{ ($.eventName = \"GetObject\") }"

  metric_transformation {
    name      = "S3GetObjectCount"
    namespace = "Sttcast/S3"
    value     = "1"
  }
}

resource "aws_sns_topic" "alarm_topic" {
  name = "sttcast-excessive-access"
}

# Alarm for excessive access to S3 bucket
# This resource creates a CloudWatch alarm that triggers if the number of GetObject events exceeds 1000 in a 5-minute period.
# The alarm is configured to send notifications to the SNS topic created above.
# The alarm is triggered if the metric "S3GetObjectCount" exceeds the threshold of 1000.
resource "aws_cloudwatch_metric_alarm" "excess_s3_get" {
  alarm_name          = "Sttcast-Excessive-GetObject"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = aws_cloudwatch_log_metric_filter.s3_get_filter.metric_transformation[0].name
  namespace           = aws_cloudwatch_log_metric_filter.s3_get_filter.metric_transformation[0].namespace
  period              = 300   # 5 minutos
  statistic           = "Sum"
  threshold           = 1000

  alarm_description = "Dispara si en 5 min hay más de 1 000 peticiones GetObject"
  alarm_actions     = [aws_sns_topic.alarm_topic.arn]
  ok_actions        = [aws_sns_topic.alarm_topic.arn]
}