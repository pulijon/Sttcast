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

# Region eu-south-2 (Spain)
variable "aws_region" {
  default = "eu-south-2"
}

variable "site" {
  description = "Dir with files to upload (required)"
  type        = string
  nullable    = false
}

variable "bucket_prefix" {
  description = "Prefijo común para todos los buckets"
  type        = string
  default     = "sttcast"
}

variable "user" {
  description = "Usuario o sufijo identificativo"
  type        = string
  nullable    = false
}

variable "podcast" {
  description = "Identificador del podcast (por ejemplo 'coffee-break')"
  type        = string
  nullable    = false
}

variable "alarm_email" {
  description = "Dirección de email para recibir las alertas"
  type        = string
  nullable    = false
}

variable "enable_monitoring" {
  description = "¿Desplegar el módulo de monitorización (CloudTrail → CloudWatch → Alarmas)?"
  type        = bool
  default     = false
}
