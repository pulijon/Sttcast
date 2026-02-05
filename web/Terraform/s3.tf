# Bucket name
resource "aws_s3_bucket" "website" {
  bucket        = local.bucket_name
  force_destroy = true
}

# Configure index and error documents
# The index document is the default page that is displayed when a user accesses the bucket's website endpoint.
# The error document is displayed when a user tries to access a page that does not exist.
resource "aws_s3_bucket_website_configuration" "website_config" {
  bucket = aws_s3_bucket.website.id

  index_document {
    suffix = "index.html"
  }

  error_document {
    key = "index.html"
  }
}

# Block public access settings
# These settings control whether public access to the bucket is allowed.
# By default, all public access is blocked.
# In this case, we are allowing public access to the bucket.
# This is necessary for the website to be publicly accessible.
resource "aws_s3_bucket_public_access_block" "public" {
  bucket = aws_s3_bucket.website.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

# Bucket policy to allow public read access
# This policy allows anyone to read the objects in the bucket.
# The policy is defined in JSON format and specifies the actions that are allowed (s3:GetObject and s3:ListBucket)
# and the resources to which the policy applies (the bucket and its objects).
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
