variable "AWS_ACCESS_KEY_ID" {
  description = "Secret Key for AWS"
  type        = string
  sensitive   = true
}

variable "AWS_SECRET_ACCESS_KEY" {
  description = "Access Key ID for AWS"
  type        = string
  sensitive   = true
}

variable "aws_region" {
  default = "eu-south-2"
}

variable "site" {
  description = "Directorio con los ficheros a subir (obligatorio)"
  type        = string
  nullable    = false
}

resource "random_id" "bucket_suffix" {
  byte_length = 6
}

locals {
  bucket_prefix = "sttcast"
  user          = "jmrobles"
  bucket_name   = "${local.bucket_prefix}-${local.user}"
}

provider "aws" {
  region     = var.aws_region
  access_key = var.AWS_ACCESS_KEY_ID
  secret_key = var.AWS_SECRET_ACCESS_KEY
}

resource "aws_s3_bucket" "website" {
  bucket        = local.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_website_configuration" "website_config" {
  bucket = aws_s3_bucket.website.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

resource "aws_s3_bucket_public_access_block" "public" {
  bucket = aws_s3_bucket.website.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "allow_public_read" {
  bucket = aws_s3_bucket.website.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement: [
      {
        Sid: "PublicRead",
        Effect: "Allow",
        Principal: "*",
        Action: [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource: [
          "${aws_s3_bucket.website.arn}",
          "${aws_s3_bucket.website.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_s3_object" "index_html" {
  bucket = aws_s3_bucket.website.id
  key    = "index.html"
  source = "${path.module}/index.html"

  content_type    = "text/html"
  storage_class   = "INTELLIGENT_TIERING"

  etag = filemd5("${path.module}/index.html")
}

resource "null_resource" "upload_content" {
  depends_on = [
    aws_s3_bucket.website,
    aws_s3_bucket_website_configuration.website_config,
    aws_s3_bucket_policy.allow_public_read,
    aws_s3_bucket_public_access_block.public
  ]

  provisioner "local-exec" {
    command = "python upload_new_files.py ${local.bucket_name} ${var.site}"
  }
}

resource "null_resource" "empty_bucket_on_destroy" {
  triggers = {
    bucket = aws_s3_bucket.website.id
  }

  provisioner "local-exec" {
    when    = destroy
    command = "aws s3 rm s3://${self.triggers.bucket} --recursive"
  }
}

output "bucket_name" {
  description = "Nombre del bucket S3"
  value       = local.bucket_name
}

output "website_url" {
  description = "URL del sitio web estático"
  value       = "http://${local.bucket_name}.s3-website.${var.aws_region}.amazonaws.com"
}
