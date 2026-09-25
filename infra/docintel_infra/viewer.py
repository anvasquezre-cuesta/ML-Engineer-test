"""The audit viewer: static files on S3 and the API behind one CloudFront."""

import aws_cdk
from aws_cdk import aws_apigatewayv2
from aws_cdk import aws_cloudfront
from aws_cdk import aws_cloudfront_origins
from aws_cdk import aws_s3
from aws_cdk import aws_s3_deployment
import constructs

# The viewer only talks to its own origin; pdf.js decodes some images in
# WebAssembly and renders pages in a blob worker.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; "
    "worker-src 'self' blob:; img-src 'self' data: blob:; "
    "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)
API_PATHS = ("/api/*", "/health")


class Viewer(constructs.Construct):
    """Serves the viewer and forwards API paths, so both share one origin.

    Attributes:
        distribution: The CloudFront distribution.
    """

    def __init__(
        self,
        scope: constructs.Construct,
        construct_id: str,
        site: aws_s3_deployment.ISource,
        http_api: aws_apigatewayv2.HttpApi,
        origin_timeout_s: int,
    ) -> None:
        """Creates the bucket, the distribution and the upload of the site.

        Args:
            scope: Parent construct.
            construct_id: Construct id.
            site: The built viewer files.
            http_api: The API that ``/api/*`` and ``/health`` go to.
            origin_timeout_s: How long CloudFront waits for the API.
        """
        super().__init__(scope, construct_id)
        bucket = aws_s3.Bucket(
            self,
            "Site",
            block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )
        headers = aws_cloudfront.ResponseHeadersPolicy(
            self,
            "Headers",
            security_headers_behavior=aws_cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=aws_cloudfront.ResponseHeadersContentSecurityPolicy(
                    content_security_policy=CONTENT_SECURITY_POLICY,
                    override=True,
                ),
                content_type_options=aws_cloudfront.ResponseHeadersContentTypeOptions(
                    override=True
                ),
                referrer_policy=aws_cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=aws_cloudfront.HeadersReferrerPolicy.NO_REFERRER,
                    override=True,
                ),
            ),
        )
        # API Gateway rejects requests that carry CloudFront's Host header.
        api = aws_cloudfront.BehaviorOptions(
            origin=aws_cloudfront_origins.HttpOrigin(
                aws_cdk.Fn.select(
                    2, aws_cdk.Fn.split("/", http_api.api_endpoint)
                ),
                protocol_policy=aws_cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
                read_timeout=aws_cdk.Duration.seconds(origin_timeout_s),
            ),
            allowed_methods=aws_cloudfront.AllowedMethods.ALLOW_ALL,
            cache_policy=aws_cloudfront.CachePolicy.CACHING_DISABLED,
            origin_request_policy=aws_cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
            viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        )
        self.distribution = aws_cloudfront.Distribution(
            self,
            "Distribution",
            default_root_object="index.html",
            default_behavior=aws_cloudfront.BehaviorOptions(
                origin=aws_cloudfront_origins.S3BucketOrigin.with_origin_access_control(
                    bucket
                ),
                viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=headers,
            ),
            additional_behaviors=dict.fromkeys(API_PATHS, api),
        )
        aws_s3_deployment.BucketDeployment(
            self,
            "Upload",
            sources=[site],
            destination_bucket=bucket,
            distribution=self.distribution,
        )
