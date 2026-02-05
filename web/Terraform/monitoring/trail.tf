# Role for CloudTrail to send logs to CloudWatch
resource "aws_iam_role" "cloudtrail_cw_role" {
  name = "CloudTrail_To_CloudWatchLogs"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "cloudtrail.amazonaws.com" }
    }]
  })
}

# Policy for CloudTrail to send logs to CloudWatch
# This policy allows CloudTrail to create log streams and put log events in the specified CloudWatch log group.
# The policy is attached to the IAM role created above.
resource "aws_iam_role_policy" "cloudtrail_cw_policy" {
  name = "CloudTrail_WriteToCWLogs"
  role = aws_iam_role.cloudtrail_cw_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"],
        Resource = aws_cloudwatch_log_group.trail_logs.arn
      }
    ]
  })
}

# CloudTrail configuration
# This resource creates a CloudTrail trail that logs API calls made in the AWS account.
# The trail is configured to log read-only events for S3 objects in the specified S3 bucket.
# The logs are sent to the specified CloudWatch log group.
resource "aws_cloudtrail" "s3_access_trail" {
  name                          = "sttcast-s3-access"
  s3_bucket_name                = aws_s3_bucket.website.bucket
  include_global_service_events = false
  is_multi_region_trail         = false

  cloud_watch_logs_group_arn = aws_cloudwatch_log_group.trail_logs.arn
  cloud_watch_logs_role_arn  = aws_iam_role.cloudtrail_cw_role.arn

  event_selector {
    read_write_type           = "ReadOnly"
    include_management_events = false

    data_resource {
      type   = "AWS::S3::Object"
      values = ["arn:aws:s3:::${aws_s3_bucket.website.bucket}/"]
    }
  }
}
