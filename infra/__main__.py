from pulumi import export, Output
import infra
import config


# Export test values
export('content_bucket_url', Output.concat('s3://', infra.content_bucket.bucket))
export('content_bucket_website_endpoint', infra.content_bucket.website_endpoint)
export('cloudfront_domain', infra.cdn.domain_name)
export('target_domain_endpoint', f'https://{config.target_domain}/')
export('identity', infra.identity.iam_arn)
export("identity.id", infra.identity.id)
export("s3", infra.content_bucket.id)
export("name", infra.content_bucket.bucket_regional_domain_name)
