module "monitoring" {
  source      = "./monitoring"
  count = var.enable_monitoring ? 1 : 0

  bucket_name = aws_s3_bucket.website.bucket
  aws_region  = var.aws_region
  alarm_email = var.alarm_email

}