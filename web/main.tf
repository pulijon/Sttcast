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

########################
# Variables (tuyas + nuevas)
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
  description = "Prefijo para el bucket S3, que tendrá la forma <prefijo>-jmrobles"
  type        = string
  nullable    = false
}

# NUEVO: dominio (GoDaddy)
variable "domain_name" {
  description = "Dominio base (ej: teleconectados.es). Si null, se usará solo el dominio cloudfront.net"
  type        = string
  default     = null
}

variable "host_name" {
  description = "Host del podcast (ej: genred). Si null y domain_name no es null, se usa el apex del dominio"
  type        = string
  default     = null
}

# NUEVO: preferencia de caché
variable "price_class" {
  description = "PriceClass_100 es lo más barato (EU/US). Sube si quieres distribución global completa."
  type        = string
  default     = "PriceClass_100"
}

########################
# Locals
########################

resource "random_id" "bucket_suffix" {
  byte_length = 6
}

locals {
  bucket_prefix = var.bucket_prefix
  user          = "jmrobles"
  bucket_name   = "${local.bucket_prefix}-${local.user}"

  fqdn = var.domain_name == null ? null : (var.host_name == null ? var.domain_name : "${var.host_name}.${var.domain_name}")
}

########################
# Providers
########################

provider "aws" {
  region     = var.aws_region
  access_key = var.AWS_ACCESS_KEY_ID
  secret_key = var.AWS_SECRET_ACCESS_KEY
}

# CloudFront requiere el cert en us-east-1
provider "aws" {
  alias      = "use1"
  region     = "us-east-1"
  access_key = var.AWS_ACCESS_KEY_ID
  secret_key = var.AWS_SECRET_ACCESS_KEY
}

########################
# S3 bucket (PRIVADO)
########################

resource "aws_s3_bucket" "website" {
  bucket        = local.bucket_name
  force_destroy = true
}

# Bloquea acceso público
resource "aws_s3_bucket_public_access_block" "public" {
  bucket = aws_s3_bucket.website.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# (Opcional) Recomendable para integridad de objetos
resource "aws_s3_bucket_versioning" "versioning" {
  bucket = aws_s3_bucket.website.id
  versioning_configuration {
    status = "Enabled"
  }
}

########################
# ACM Certificate (solo si domain_name no es null)
########################

resource "aws_acm_certificate" "cert" {
  count             = local.fqdn == null ? 0 : 1
  provider          = aws.use1
  domain_name       = local.fqdn
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# Aquí NO creamos registros DNS (GoDaddy). Te los damos por output.
resource "aws_acm_certificate_validation" "cert" {
  count    = local.fqdn == null ? 0 : 1
  provider = aws.use1

  certificate_arn = aws_acm_certificate.cert[0].arn
  # Importante: esto queda pendiente hasta que crees los CNAME en GoDaddy.
  validation_record_fqdns = []
}

########################
# CloudFront OAC
########################

resource "aws_cloudfront_origin_access_control" "oac" {
  name                              = "${local.bucket_name}-oac"
  description                       = "OAC for private S3 origin"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

########################
# CloudFront Distribution
########################

resource "aws_cloudfront_distribution" "cdn" {
  enabled         = true
  comment         = "sttcast CDN for ${local.bucket_name}"
  price_class     = var.price_class
  is_ipv6_enabled = true

  aliases = local.fqdn == null ? [] : [local.fqdn]

  origin {
    domain_name              = aws_s3_bucket.website.bucket_regional_domain_name
    origin_id                = "s3-${aws_s3_bucket.website.id}"
    origin_access_control_id = aws_cloudfront_origin_access_control.oac.id
  }

  default_root_object = "index.html"

  default_cache_behavior {
    target_origin_id       = "s3-${aws_s3_bucket.website.id}"
    viewer_protocol_policy = "redirect-to-https"

    allowed_methods = ["GET", "HEAD", "OPTIONS"]
    cached_methods  = ["GET", "HEAD"]

    compress = true

    # Managed-CachingOptimized
    cache_policy_id = "658327ea-f89d-4fab-a63d-7e88639e58f6"

    # Managed-CORS-S3Origin (cómodo para HTML/JS; si no lo necesitas, se puede cambiar)
    origin_request_policy_id = "88a5eaf4-2fd4-4709-b370-b4c650ea3fcf"
  }

  # Para que / y rutas “no encontradas” devuelvan index.html (útil si tu index navega por JS)
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
    cloudfront_default_certificate = local.fqdn == null ? true : false

    # Cuando el cert esté "Issued", usa este
    acm_certificate_arn      = local.fqdn == null ? null : aws_acm_certificate.cert[0].arn
    ssl_support_method       = local.fqdn == null ? null : "sni-only"
    minimum_protocol_version = local.fqdn == null ? null : "TLSv1.2_2021"
  }
}

########################
# Bucket policy: permitir SOLO a CloudFront leer
########################

resource "aws_s3_bucket_policy" "allow_cloudfront_read" {
  bucket = aws_s3_bucket.website.id

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "AllowCloudFrontServicePrincipalReadOnly",
        Effect    = "Allow",
        Principal = { Service = "cloudfront.amazonaws.com" },
        Action    = ["s3:GetObject"],
        Resource  = ["${aws_s3_bucket.website.arn}/*"],
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.cdn.arn
          }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.public]
}

########################
# Upload contenido (local-exec)
# Usa publish_episode.py que genera RSS y sube archivos
########################

resource "null_resource" "upload_content" {
  depends_on = [
    aws_s3_bucket.website,
    aws_s3_bucket_policy.allow_cloudfront_read
  ]

  provisioner "local-exec" {
    command = "python publish_episode.py --skip-rss"
    # Nota: --skip-rss porque el RSS debe generarse manualmente
    # antes del terraform apply para incluir metadatos correctos.
    # Para subir con RSS: python publish_episode.py
  }
}

########################
# Empty bucket on destroy
########################

resource "null_resource" "empty_bucket_on_destroy" {
  triggers = {
    bucket = aws_s3_bucket.website.id
  }

  provisioner "local-exec" {
    when    = destroy
    command = "aws s3 rm s3://${self.triggers.bucket} --recursive"
  }
}

########################
# Outputs
########################

output "bucket_name" {
  description = "Nombre del bucket S3"
  value       = local.bucket_name
}

output "cloudfront_domain" {
  description = "Dominio de CloudFront"
  value       = aws_cloudfront_distribution.cdn.domain_name
}

output "cloudfront_distribution_id" {
  description = "ID de la distribución CloudFront (para invalidar caché)"
  value       = aws_cloudfront_distribution.cdn.id
}

output "public_base_url" {
  description = "URL pública base. Si hay dominio, úsalo; si no, usa cloudfront.net"
  value       = local.fqdn == null ? "https://${aws_cloudfront_distribution.cdn.domain_name}" : "https://${local.fqdn}"
}

# IMPORTANTE: valores para crear CNAMEs en GoDaddy (validación ACM)
output "acm_dns_validation_records" {
  description = "Crea estos CNAME en GoDaddy para validar el certificado (solo si usas domain_name)"
  value = local.fqdn == null ? [] : [
    for dvo in aws_acm_certificate.cert[0].domain_validation_options : {
      name  = dvo.resource_record_name
      type  = dvo.resource_record_type
      value = dvo.resource_record_value
    }
  ]
}

# IMPORTANTE: records para apuntar tu host a CloudFront (GoDaddy)
output "godaddy_dns_for_cloudfront" {
  description = "En GoDaddy: crea un CNAME del host hacia el dominio cloudfront (si usas subdominio). Para apex, necesitarías ALIAS/ANAME (depende de GoDaddy)."
  value = local.fqdn == null ? null : {
    fqdn                 = local.fqdn
    recommended_record   = "CNAME"
    recommended_name     = var.host_name == null ? "@" : var.host_name
    recommended_value    = aws_cloudfront_distribution.cdn.domain_name
  }
}
