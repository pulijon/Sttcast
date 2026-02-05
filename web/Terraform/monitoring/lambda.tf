# Role for Lambda function to close S3 bucket
# This role allows the Lambda function to assume the role and perform actions on S3.
# The role is created with a trust policy that allows the Lambda service to assume the role.
# The role is attached to the Lambda function and has permissions to put a bucket policy on the specified S3 bucket.
resource "aws_iam_role" "lambda_role" {
  name = "Lambda_CloseS3Bucket"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action    = "sts:AssumeRole",
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

# Policy for Lambda function to close S3 bucket
# This policy allows the Lambda function to put a bucket policy on the specified S3 bucket.
# The policy is attached to the IAM role created above.
resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Policy for Lambda function to close S3 bucket
# This policy allows the Lambda function to put a bucket policy on the specified S3 bucket.
# The policy is attached to the IAM role created above.
resource "aws_iam_role_policy" "lambda_s3_block" {
  name = "LambdaBlockS3"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect   = "Allow",
        Action   = ["s3:PutBucketPolicy"],
        Resource = aws_s3_bucket.website.arn
      }
    ]
  })
}

# Lambda function to close S3 bucket
# This resource creates a Lambda function that is triggered by an SNS topic.
# The function is responsible for closing the S3 bucket when the SNS topic is triggered.
# The function is created with the specified runtime, handler, and role.
# The function code is provided in a ZIP file.
# The function is triggered by the SNS topic created above.
resource "aws_lambda_function" "close_bucket" {
  filename         = "lambda_close_bucket.zip"       # tu ZIP con el código
  function_name    = "CloseSttcastBucketOnAlarm"
  handler          = "index.handler"
  runtime          = "python3.9"
  role             = aws_iam_role.lambda_role.arn
  source_code_hash = filebase64sha256("lambda_close_bucket.zip")
}

# SNS topic for alarm
# This resource creates an SNS topic that is used to trigger the Lambda function.
# The topic is created with the specified name.
resource "aws_sns_topic_subscription" "lambda_sub" {
  topic_arn = aws_sns_topic.alarm_topic.arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.close_bucket.arn
}

# This resource allows the Lambda function to be triggered by the SNS topic.
# The permission is created with the specified statement ID, action, function name, principal, and source ARN.
# The statement ID is used to identify the permission.
# The action is set to "lambda:InvokeFunction" to allow the Lambda function to be invoked.
# The function name is the name of the Lambda function created above.
resource "aws_lambda_permission" "allow_sns" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.close_bucket.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = aws_sns_topic.alarm_topic.arn
}