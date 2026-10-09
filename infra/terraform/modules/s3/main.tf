variable "env" { type = string }

resource "aws_s3_bucket" "attachments" {
  bucket = "smart-${var.env}-attachments"
}

resource "aws_s3_bucket_versioning" "attachments" {
  bucket = aws_s3_bucket.attachments.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "attachments" {
  bucket = aws_s3_bucket.attachments.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_public_access_block" "attachments" {
  bucket                  = aws_s3_bucket.attachments.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Language packs: en.json, am.json, or.json — uploaded separately, not managed by Terraform
resource "aws_s3_object" "locale_placeholder" {
  for_each     = toset(["en", "am", "or"])
  bucket       = aws_s3_bucket.attachments.id
  key          = "locales/${each.key}.json"
  content      = jsonencode({ "_placeholder" : "upload real locale file" })
  content_type = "application/json"
}

output "bucket_name" { value = aws_s3_bucket.attachments.id }
output "bucket_arn" { value = aws_s3_bucket.attachments.arn }
