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
