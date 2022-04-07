import pulumi_aws
import config
from pulumi import ResourceOptions


def get_domain_and_subdomain(domain):
    """
    Returns the subdomain and the parent domain.
    """

    parts = domain.split('.')
    if len(parts) < 2:
        raise Exception(f'No TLD found on ${domain}')
    if len(parts) == 2:
        return '', domain
    subdomain = parts[0]
    parts.pop(0)
    return subdomain, '.'.join(parts) + '.'


# Create Cloudfront Identity
identity = pulumi_aws.cloudfront.OriginAccessIdentity(
    "S3-identity",
    comment="S3-access"
)


# Create an S3 bucket configured as a website bucket.
content_bucket = pulumi_aws.s3.Bucket(
    'contentBucket',
    bucket=config.target_domain,
    website=pulumi_aws.s3.BucketWebsiteArgs(
        index_document='index.html'
    ),
    acl="private",
    versioning=pulumi_aws.s3.BucketVersioningArgs(enabled=True),
    tags=config.tags
)


# def crawl_directory(content_dir, f):
#    """
#    Crawl `content_dir` (including subdirectories) and apply the function `f` to each file.
#    """
#    for file in os.listdir(content_dir):
#        filepath = os.path.join(content_dir, file)
#
#        if os.path.isdir(filepath):
#            crawl_directory(filepath, f)
#        elif os.path.isfile(filepath):
#            f(filepath)
#
# web_contents_root_path = os.path.join(os.getcwd(), path_to_website_contents)
# def bucket_object_converter(filepath):
#    """
#    Takes a file path and returns an bucket object managed by Pulumi
#    """
#    relative_path = filepath.replace(web_contents_root_path + '/', '')
#    # Determine the mimetype using the `mimetypes` module.
#    mime_type, _ = mimetypes.guess_type(filepath)
#    content_file = pulumi_aws.s3.BucketObject(
#        relative_path,
#        key=relative_path,
#        acl='public-read',
#        bucket=content_bucket.id,
#        content_type=mime_type,
#        source=FileAsset(filepath),
#        opts=ResourceOptions(parent=content_bucket)
#    )

# Crawl the web content root path and convert the file paths to S3 object resources.
# crawl_directory(web_contents_root_path, bucket_object_converter)

TEN_MINUTES = 60 * 10

# Provision a certificate if the arn is not provided via configuration.
if config.certificate_arn is None:
    # CloudFront is in us-east-1 and expects the ACM certificate to also be in us-east-1.
    # So, we create an east_region provider specifically for these operations.
    east_region = pulumi_aws.Provider('east', profile=pulumi_aws.config.profile, region='us-east-1')

    # Get a certificate for our website domain name.
    certificate = pulumi_aws.acm.Certificate(
        'certificate',
        domain_name=config.target_domain,
        validation_method='DNS',
        opts=ResourceOptions(provider=east_region),
        tags=config.tags
    )

    # Find the Route 53 hosted zone so we can create the validation record.
    subdomain, parent_domain = get_domain_and_subdomain(config.target_domain)
    hzid = pulumi_aws.route53.get_zone(name=parent_domain).id

    # Create a validation record to prove that we own the domain.
    cert_validation_domain = pulumi_aws.route53.Record(
        f'{config.target_domain}-validation',
        name=certificate.domain_validation_options.apply(
            lambda o: o[0].resource_record_name),
        zone_id=hzid,
        type=certificate.domain_validation_options.apply(
            lambda o: o[0].resource_record_type),
        records=[certificate.domain_validation_options.apply(
            lambda o: o[0].resource_record_value)],
        ttl=TEN_MINUTES
    )

    # Create a special resource to await complete validation of the cert.
    # Note that this is not a real AWS resource.
    cert_validation = pulumi_aws.acm.CertificateValidation(
        'certificateValidation',
        certificate_arn=certificate.arn,
        validation_record_fqdns=[cert_validation_domain.fqdn],
        opts=ResourceOptions(provider=east_region)
    )

    certificate_arn = cert_validation.certificate_arn

# Create a logs bucket for the CloudFront logs
logs_bucket = pulumi_aws.s3.Bucket(
    'requestLogs',
    bucket=f'{config.target_domain}-logs',
    acl='private',
    tags=config.tags
)

# Create the CloudFront distribution
cdn = pulumi_aws.cloudfront.Distribution(
    'cdn',
    enabled=True,
    aliases=[
        config.target_domain
    ],
    origins=[pulumi_aws.cloudfront.DistributionOriginArgs(
        origin_id=content_bucket.arn,
        domain_name=content_bucket.bucket_regional_domain_name,
        s3_origin_config=pulumi_aws.cloudfront.DistributionOriginS3OriginConfigArgs(
            origin_access_identity=identity.cloudfront_access_identity_path,
        )
    )],
    default_root_object='index.html',
    default_cache_behavior=pulumi_aws.cloudfront.DistributionDefaultCacheBehaviorArgs(
        target_origin_id=content_bucket.arn,
        viewer_protocol_policy='redirect-to-https',
        allowed_methods=['GET', 'HEAD', 'OPTIONS'],
        cached_methods=['GET', 'HEAD', 'OPTIONS'],
        forwarded_values=pulumi_aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesArgs(
            cookies=pulumi_aws.cloudfront.DistributionDefaultCacheBehaviorForwardedValuesCookiesArgs(forward='none'),
            query_string=False,
        ),
        min_ttl=0,
        default_ttl=TEN_MINUTES,
        max_ttl=TEN_MINUTES,
    ),
    # PriceClass_100 is the lowest cost tier (US/EU only).
    price_class='PriceClass_100',
    # Use the certificate we generated for this distribution.
    viewer_certificate=pulumi_aws.cloudfront.DistributionViewerCertificateArgs(
        acm_certificate_arn=certificate_arn,
        minimum_protocol_version='TLSv1.2_2021',
        ssl_support_method='sni-only',
    ),
    restrictions=pulumi_aws.cloudfront.DistributionRestrictionsArgs(
        geo_restriction=pulumi_aws.cloudfront.DistributionRestrictionsGeoRestrictionArgs(
            restriction_type='none'
        )
    ),
    # Put access logs in the log bucket we created earlier.
    logging_config=pulumi_aws.cloudfront.DistributionLoggingConfigArgs(
        bucket=logs_bucket.bucket_domain_name,
        include_cookies=False,
        prefix=f'${config.target_domain}/',
    ),
    tags=config.tags,
    # CloudFront typically takes 15 minutes to fully deploy a new distribution.
    # Skip waiting for that to complete.
    wait_for_deployment=False)


def create_alias_record(target_domain, distribution):
    """
    Create a Route 53 Alias A record from the target domain name to the CloudFront distribution.
    """
    subdomain, parent_domain = get_domain_and_subdomain(target_domain)
    hzid = pulumi_aws.route53.get_zone(name=parent_domain).id
    return pulumi_aws.route53.Record(
        target_domain,
        name=subdomain,
        zone_id=hzid,
        type='A',
        aliases=[
            pulumi_aws.route53.RecordAliasArgs(
                name=distribution.domain_name,
                zone_id=distribution.hosted_zone_id,
                evaluate_target_health=True,
            )
        ]
    )


alias_a_record = create_alias_record(config.target_domain, cdn)

# Policy for bucket
allow_cloudfront = pulumi_aws.iam.get_policy_document_output(
    statements=[pulumi_aws.iam.GetPolicyDocumentStatementArgs(
        principals=[pulumi_aws.iam.GetPolicyDocumentStatementPrincipalArgs(
            type="AWS",
            identifiers=[identity.iam_arn],
        )],
        actions=[
            "s3:GetObject",
            "s3:ListBucket",
        ],
        resources=[
            content_bucket.arn,
            content_bucket.arn.apply(lambda arn: f"{arn}/*"),
        ],
    )]
)
allow_cdn = pulumi_aws.s3.BucketPolicy(
    "allowAccessFromAnotherAccountBucketPolicy",
    bucket=content_bucket.id,
    policy=allow_cloudfront.json)
