# Name for the bucket
locals {
  bucket_name = "${var.bucket_prefix}-${var.user}-${var.podcast}"
}