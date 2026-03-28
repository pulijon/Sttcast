terraform {
  required_version = ">= 1.4.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
}

moved {
  from = aws_s3_bucket.website
  to   = aws_s3_bucket.website[0]
}

moved {
  from = aws_s3_bucket_public_access_block.public
  to   = aws_s3_bucket_public_access_block.public[0]
}

moved {
  from = aws_s3_bucket_versioning.versioning
  to   = aws_s3_bucket_versioning.versioning[0]
}

moved {
  from = aws_s3_bucket.logs
  to   = aws_s3_bucket.logs[0]
}

moved {
  from = aws_s3_bucket_ownership_controls.logs
  to   = aws_s3_bucket_ownership_controls.logs[0]
}

moved {
  from = aws_s3_bucket_public_access_block.logs_public
  to   = aws_s3_bucket_public_access_block.logs_public[0]
}

moved {
  from = aws_s3_bucket_acl.logs
  to   = aws_s3_bucket_acl.logs[0]
}

moved {
  from = aws_cloudfront_origin_access_control.oac
  to   = aws_cloudfront_origin_access_control.oac[0]
}

moved {
  from = aws_cloudfront_distribution.cdn
  to   = aws_cloudfront_distribution.cdn[0]
}

moved {
  from = aws_s3_bucket_policy.allow_cloudfront_read
  to   = aws_s3_bucket_policy.allow_cloudfront_read[0]
}

moved {
  from = null_resource.upload_content
  to   = null_resource.upload_content[0]
}

moved {
  from = null_resource.empty_bucket_on_destroy
  to   = null_resource.empty_bucket_on_destroy[0]
}

########################
# Variables
########################

variable "AWS_ACCESS_KEY_ID" {
  description = "Access Key ID for AWS"
  type        = string
  sensitive   = true
}

variable "AWS_SECRET_ACCESS_KEY" {
  description = "Secret Key for AWS"
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

variable "bucket_prefix" {
  description = "Prefijo para el bucket S3, que tendra la forma <prefijo>-jmrobles"
  type        = string
  nullable    = false
}

variable "deployment_mode" {
  description = "Modo de despliegue: none | s3_public | s3_private | cloudfront"
  type        = string
  default     = "cloudfront"

  validation {
    condition = contains([
      "none",
      "s3_public",
      "s3_private",
      "cloudfront",
    ], var.deployment_mode)
    error_message = "deployment_mode must be one of: none, s3_public, s3_private, cloudfront."
  }
}

variable "domain_name" {
  description = "Dominio base (ej: teleconectados.es). Solo se usa en modo cloudfront"
  type        = string
  default     = null
}

variable "host_name" {
  description = "Host del podcast (ej: genred). Si null y domain_name no es null, se usa el apex del dominio"
  type        = string
  default     = null
}

variable "price_class" {
  description = "PriceClass_100 es lo mas barato (EU/US). Sube si quieres distribucion global completa."
  type        = string
  default     = "PriceClass_100"
}

variable "log_retention_days" {
  description = "Dias que se conservan los logs de CloudFront antes de borrarlos (0 = nunca borrar)"
  type        = number
  default     = 30
}

########################
# Locals
########################

resource "random_id" "bucket_suffix" {
  byte_length = 6
}

locals {
  bucket_prefix         = var.bucket_prefix
  user                  = "jmrobles"
  bucket_name           = "${local.bucket_prefix}-${local.user}"
  create_website_bucket = var.deployment_mode != "none"
  bucket_is_public      = var.deployment_mode == "s3_public"
  bucket_is_private     = contains(["s3_private", "cloudfront"], var.deployment_mode)
  create_cloudfront     = var.deployment_mode == "cloudfront"
  create_certificate    = local.create_cloudfront && var.domain_name != null

  fqdn = local.create_certificate ? (
    var.host_name == null ? var.domain_name : "${var.host_name}.${var.domain_name}"
  ) : null
}

########################
# Providers
########################

provider "aws" {
  region     = var.aws_region
  access_key = var.AWS_ACCESS_KEY_ID
  secret_key = var.AWS_SECRET_ACCESS_KEY
}

provider "aws" {
  alias      = "use1"
  region     = "us-east-1"
  access_key = var.AWS_ACCESS_KEY_ID
  secret_key = var.AWS_SECRET_ACCESS_KEY
}

########################
# Bucket principal
########################

resource "aws_s3_bucket" "website" {
  count         = local.create_website_bucket ? 1 : 0
  bucket        = local.bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "public" {
  count  = local.create_website_bucket ? 1 : 0
  bucket = aws_s3_bucket.website[0].id

  block_public_acls       = local.bucket_is_private
  block_public_policy     = local.bucket_is_private
  ignore_public_acls      = local.bucket_is_private
  restrict_public_buckets = local.bucket_is_private
}

resource "aws_s3_bucket_versioning" "versioning" {
  count  = local.create_website_bucket ? 1 : 0
  bucket = aws_s3_bucket.website[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_website_configuration" "website" {
  count  = local.bucket_is_public ? 1 : 0
  bucket = aws_s3_bucket.website[0].id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

########################
# Logs de CloudFront
########################

resource "aws_s3_bucket" "logs" {
  count         = local.create_cloudfront ? 1 : 0
  provider      = aws.use1
  bucket        = "${local.bucket_name}-logs"
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "logs" {
  count    = local.create_cloudfront ? 1 : 0
  provider = aws.use1
  bucket   = aws_s3_bucket.logs[0].id

  rule {
    object_ownership = "ObjectWriter"
  }
}

resource "aws_s3_bucket_public_access_block" "logs_public" {
  count    = local.create_cloudfront ? 1 : 0
  provider = aws.use1
  bucket   = aws_s3_bucket.logs[0].id

  block_public_acls       = false
  block_public_policy     = true
  ignore_public_acls      = false
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "logs_lifecycle" {
  provider = aws.use1
  count    = local.create_cloudfront && var.log_retention_days > 0 ? 1 : 0
  bucket   = aws_s3_bucket.logs[0].id

  rule {
    id     = "delete-old-logs"
    status = "Enabled"

    filter {
      prefix = "cloudfront/"
    }

    expiration {
      days = var.log_retention_days
    }
  }
}

resource "aws_s3_bucket_acl" "logs" {
  count    = local.create_cloudfront ? 1 : 0
  provider = aws.use1
  depends_on = [
    aws_s3_bucket_ownership_controls.logs,
    aws_s3_bucket_public_access_block.logs_public,
  ]
  bucket = aws_s3_bucket.logs[0].id

  access_control_policy {
    grant {
      grantee {
        type = "CanonicalUser"
        id   = data.aws_canonical_user_id.current.id
      }
      permission = "FULL_CONTROL"
    }

    grant {
      grantee {
        type = "CanonicalUser"
        id   = data.aws_cloudfront_log_delivery_canonical_user_id.cloudfront.id
      }
      permission = "FULL_CONTROL"
    }

    owner {
      id = data.aws_canonical_user_id.current.id
    }
  }
}

data "aws_canonical_user_id" "current" {}

data "aws_cloudfront_log_delivery_canonical_user_id" "cloudfront" {}

########################
# ACM Certificate
########################

resource "aws_acm_certificate" "cert" {
  count             = local.create_certificate ? 1 : 0
  provider          = aws.use1
  domain_name       = local.fqdn
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_acm_certificate_validation" "cert" {
  count    = local.create_certificate ? 1 : 0
  provider = aws.use1

  certificate_arn         = aws_acm_certificate.cert[0].arn
  validation_record_fqdns = []
}

########################
# CloudFront
########################

resource "aws_cloudfront_origin_access_control" "oac" {
  count                             = local.create_cloudfront ? 1 : 0
  name                              = "${local.bucket_name}-oac"
  description                       = "OAC for private S3 origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "cdn" {
  count           = local.create_cloudfront ? 1 : 0
  enabled         = true
  comment         = "sttcast CDN for ${local.bucket_name}"
  price_class     = var.price_class
  is_ipv6_enabled = true
  depends_on      = [aws_s3_bucket_acl.logs]

  aliases = local.fqdn == null ? [] : [local.fqdn]

  logging_config {
    include_cookies = false
    bucket          = aws_s3_bucket.logs[0].bucket_regional_domain_name
    prefix          = "cloudfront/"
  }

  origin {
    domain_name              = aws_s3_bucket.website[0].bucket_regional_domain_name
    origin_id                = "s3-${aws_s3_bucket.website[0].id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.oac[0].id
  }

  default_root_object = "index.html"

  default_cache_behavior {
    target_origin_id       = "s3-${aws_s3_bucket.website[0].id}"
    viewer_protocol_policy = "redirect-to-https"

    allowed_methods = ["GET", "HEAD", "OPTIONS"]
    cached_methods  = ["GET", "HEAD"]

    compress = true

    cache_policy_id          = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    origin_request_policy_id = "88a5eaf4-2fd4-4709-b370-b4c650ea3fcf"
  }

  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = local.fqdn == null
    acm_certificate_arn            = local.fqdn == null ? null : aws_acm_certificate.cert[0].arn
    ssl_support_method             = local.fqdn == null ? null : "sni-only"
    minimum_protocol_version       = local.fqdn == null ? null : "TLSv1.2_2021"
  }
}

########################
# Politica del bucket
########################

resource "aws_s3_bucket_policy" "allow_cloudfront_read" {
  count  = local.create_cloudfront || local.bucket_is_public ? 1 : 0
  bucket = aws_s3_bucket.website[0].id

  policy = local.create_cloudfront ? jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipalReadOnly",
        Effect    = "Allow",
        Principal = { Service = "cloudfront.amazonaws.com" },
        Action    = ["s3:GetObject"],
        Resource  = ["${aws_s3_bucket.website[0].arn}/*"],
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.cdn[0].arn
          }
        }
      }
    ]
    }) : jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "AllowPublicReadOnly",
        Effect    = "Allow",
        Principal = "*",
        Action    = ["s3:GetObject"],
        Resource  = ["${aws_s3_bucket.website[0].arn}/*"],
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.public]
}

########################
# Upload contenido
########################

resource "null_resource" "upload_content" {
  count = local.create_website_bucket ? 1 : 0
  depends_on = [
    aws_s3_bucket.website,
    aws_s3_bucket_policy.allow_cloudfront_read,
    aws_s3_bucket_website_configuration.website,
  ]

  provisioner "local-exec" {
    command = "python publish_episode.py --skip-rss"
  }
}

########################
# Empty bucket on destroy
########################

resource "null_resource" "empty_bucket_on_destroy" {
  count = local.create_website_bucket ? 1 : 0

  triggers = {
    bucket = aws_s3_bucket.website[0].id
  }

  provisioner "local-exec" {
    when    = destroy
    command = "aws s3 rm s3://${self.triggers.bucket} --recursive"
  }
}

########################
# Outputs
########################

output "deployment_mode" {
  description = "Modo de despliegue efectivo"
  value       = var.deployment_mode
}

output "bucket_name" {
  description = "Nombre del bucket S3"
  value       = local.create_website_bucket ? aws_s3_bucket.website[0].id : null
}

output "cloudfront_domain" {
  description = "Dominio de CloudFront"
  value       = local.create_cloudfront ? aws_cloudfront_distribution.cdn[0].domain_name : null
}

output "cloudfront_distribution_id" {
  description = "ID de la distribucion CloudFront (para invalidar cache)"
  value       = local.create_cloudfront ? aws_cloudfront_distribution.cdn[0].id : null
}

output "public_base_url" {
  description = "URL publica base segun el modo configurado"
  value = !local.create_website_bucket ? null : (
    local.create_cloudfront
    ? (local.fqdn == null ? "https://${aws_cloudfront_distribution.cdn[0].domain_name}" : "https://${local.fqdn}")
    : (local.bucket_is_public ? "http://${aws_s3_bucket_website_configuration.website[0].website_endpoint}" : null)
  )
}

output "acm_dns_validation_records" {
  description = "Create these CNAME records in your DNS provider to validate the certificate (only if domain_name is set)"
  value = local.create_certificate ? [
    for dvo in aws_acm_certificate.cert[0].domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ] : []
}

output "dns_records_for_cloudfront" {
  description = "Create a DNS record that points your chosen host to the CloudFront domain (for subdomains, use CNAME; for apex, use your provider's supported alias-style record)"
  value = local.fqdn == null ? null : {
    fqdn               = local.fqdn
    recommended_record = "CNAME"
    recommended_name   = var.host_name == null ? "@" : var.host_name
    recommended_value  = aws_cloudfront_distribution.cdn[0].domain_name
  }
}

output "logs_bucket" {
  description = "Bucket S3 donde se almacenan los logs de CloudFront"
  value       = local.create_cloudfront ? aws_s3_bucket.logs[0].id : null
}

output "logs_retention_days" {
  description = "Dias de retencion de logs configurados"
  value       = local.create_cloudfront ? var.log_retention_days : null
}
