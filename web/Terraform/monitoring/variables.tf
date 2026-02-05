variable "bucket_name" {
  description = "Nombre del bucket S3 a monitorizar"
  type        = string
}

variable "aws_region" {
  description = "Región AWS donde existe el bucket"
  type        = string
}

variable "alarm_email" {
  description = "Dirección de correo que recibirá las alarmas"
  type        = string
}
