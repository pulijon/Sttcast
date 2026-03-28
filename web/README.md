# Web Deployment

## Caution

Publishing files to AWS has an associated cost for storage, requests, data transfer, CloudFront traffic, and optional certificate-related operations.

You are responsible for monitoring those costs and applying the appropriate safeguards before running `terraform apply`.

## Purpose

This directory contains the infrastructure and helper scripts used to publish podcast assets and generated HTML content to AWS.

The deployment is driven by Terraform in [main.tf](/home/jmrobles/Podcasts/Teleconectados/Sttcast/web/main.tf) and by environment variables stored in [.env/aws.env](/home/jmrobles/Podcasts/Teleconectados/Sttcast/.env/aws.env). The helper script [load_env.sh](/home/jmrobles/Podcasts/Teleconectados/Sttcast/web/load_env.sh) converts that environment file into `terraform.tfvars`.

The design supports multiple deployment modes so different podcast collections can choose different publication strategies without maintaining separate Terraform code.

## High-Level Structure

The Terraform file is organized into these sections:

1. Terraform and provider requirements.
2. State migration blocks using `moved`.
3. Input variables.
4. Derived configuration in `locals`.
5. AWS providers.
6. Main S3 website bucket resources.
7. CloudFront log bucket resources.
8. ACM certificate resources.
9. CloudFront distribution resources.
10. Bucket access policy.
11. Content upload helper resources.
12. Destroy-time cleanup helper.
13. Outputs.

## Deployment Modes

The key variable is `deployment_mode`.

Supported values are:

1. `none`
2. `s3_public`
3. `s3_private`
4. `cloudfront`

### `none`

Terraform does not create the website bucket, CloudFront, ACM, or log buckets.

### `s3_public`

Terraform creates a public S3 bucket configured as a static website endpoint.

### `s3_private`

Terraform creates a private S3 bucket but does not expose it publicly and does not create CloudFront.

### `cloudfront`

Terraform creates:

1. A private S3 bucket for site content.
2. A dedicated S3 bucket for CloudFront access logs.
3. A CloudFront Origin Access Control.
4. A CloudFront distribution.
5. An ACM certificate if `domain_name` is provided.

## Input Variables

The most relevant variables in [main.tf](/home/jmrobles/Podcasts/Teleconectados/Sttcast/web/main.tf) are:

1. `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`: AWS credentials.
2. `aws_region`: primary AWS region.
3. `site`: local content directory.
4. `bucket_prefix`: base name for the bucket.
5. `deployment_mode`: deployment strategy.
6. `domain_name`: optional base domain for CloudFront.
7. `host_name`: optional host under the base domain.
8. `price_class`: CloudFront price/performance class.
9. `log_retention_days`: retention for CloudFront access logs.

## How `locals` Drive the Configuration

The `locals` block translates raw variables into booleans that decide which resources exist:

1. `create_website_bucket`
2. `bucket_is_public`
3. `bucket_is_private`
4. `create_cloudfront`
5. `create_certificate`
6. `fqdn`

This keeps conditional logic centralized instead of scattering long expressions across all resources.

## How Resources Are Enabled or Disabled

Most resources use `count`.

Typical examples:

1. Main website bucket: `count = local.create_website_bucket ? 1 : 0`.
2. S3 website configuration: `count = local.bucket_is_public ? 1 : 0`.
3. CloudFront resources: `count = local.create_cloudfront ? 1 : 0`.
4. ACM resources: `count = local.create_certificate ? 1 : 0`.

## Main S3 Bucket

The main site bucket is defined by `aws_s3_bucket.website`.

Related resources:

1. `aws_s3_bucket_public_access_block.public` controls public access restrictions.
2. `aws_s3_bucket_versioning.versioning` enables versioning.
3. `aws_s3_bucket_website_configuration.website` exists only in `s3_public` mode.

## CloudFront Log Bucket

When `deployment_mode = cloudfront`, Terraform creates a separate bucket for CloudFront access logs, with ownership controls, ACL, and optional retention lifecycle.

## ACM Certificates

If `deployment_mode = cloudfront` and `domain_name` is not null, Terraform creates an ACM certificate in `us-east-1`.

The certificate validation DNS records are exposed as outputs so they can be added manually in your DNS provider.

## CloudFront Distribution

When `deployment_mode = cloudfront`, Terraform creates:

1. An Origin Access Control.
2. A CloudFront distribution pointing to the private S3 bucket.
3. Logging to the dedicated log bucket.
4. Optional aliases and ACM certificate binding.

## Bucket Policy Behavior

The bucket policy changes depending on the selected mode.

1. `cloudfront`: allows read access only from the specific CloudFront distribution.
2. `s3_public`: allows anonymous read access.
3. `s3_private`: no public read policy.

## Upload and Destroy Helpers

Two `null_resource` blocks provide operational helpers:

1. `upload_content` runs `python publish_episode.py --skip-rss` after bucket setup.
2. `empty_bucket_on_destroy` removes bucket contents before destroy.

## Outputs

The main outputs are:

1. `deployment_mode`
2. `bucket_name`
3. `cloudfront_domain`
4. `cloudfront_distribution_id`
5. `public_base_url`
6. `acm_dns_validation_records`
7. `dns_records_for_cloudfront`
8. `logs_bucket`
9. `logs_retention_days`

Outputs return `null` or `[]` when a resource is not created in the selected mode.

## How `moved` Works

The `moved` blocks near the top of [main.tf](/home/jmrobles/Podcasts/Teleconectados/Sttcast/web/main.tf) are critical for safe refactoring.

### Why They Were Needed

Before refactoring, several resources existed without `count`, for example:

```hcl
aws_s3_bucket.website
aws_cloudfront_distribution.cdn
null_resource.upload_content
```

After introducing `count` for mode-based creation, addresses became indexed:

```hcl
aws_s3_bucket.website[0]
aws_cloudfront_distribution.cdn[0]
null_resource.upload_content[0]
```

Without `moved`, Terraform would interpret this as old resources disappearing and new resources being created, often producing replacement plans.

### What `moved` Does

A block such as:

```hcl
moved {
  from = aws_s3_bucket.website
  to   = aws_s3_bucket.website[0]
}
```

instructs Terraform to migrate state addresses from old to new logical addresses.

This is a state mapping operation, not an infrastructure recreation.

### What `moved` Does Not Do

`moved` does not automatically prevent all future replacements. If you introduce a real force-replace change, Terraform may still need to recreate resources.

It only solves address migration in state when resource identity remains the same.

## Environment File and `load_env.sh`

The file [.env/aws.env](/home/jmrobles/Podcasts/Teleconectados/Sttcast/.env/aws.env) is the human-edited source of truth.

The script [load_env.sh](/home/jmrobles/Podcasts/Teleconectados/Sttcast/web/load_env.sh):

1. Maps environment keys to Terraform variables.
2. Validates `DEPLOYMENT_MODE`.
3. Writes `null` for empty `DOMAIN_NAME` or `HOST_NAME`.
4. Regenerates `terraform.tfvars` from scratch.

Typical workflow:

```bash
cd web
./load_env.sh
terraform plan
terraform apply
```

## Safe Usage Notes

Before `terraform apply`:

1. Run `./load_env.sh`.
2. Inspect `terraform.tfvars`.
3. Run `terraform plan`.
4. Confirm there is no unexpected destruction.

This is especially important when changing `deployment_mode`, because mode changes can imply real resource creation or removal depending on existing state.

## Recommended Maintenance Strategy

Treat this stack as three layers:

1. `.env/aws.env` defines intent.
2. `load_env.sh` translates intent into Terraform input.
3. `main.tf` translates input into conditionally created infrastructure.

This separation reduces risk and keeps collection-specific changes in environment configuration rather than Terraform logic.
