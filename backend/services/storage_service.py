"""
services/storage_service.py - File Storage (S3-compatible object storage)

Uses CESNET S3 (e-INFRA) in production via boto3.
Configuration is driven entirely from environment variables (S3_* in .env).

We store:
- Screenshots (.png)
- Raw HTML dumps (.html)
- PDF evidence (.pdf)
- Structured document JSON (.json)

Files are organized by: source_id / job_id / filename
"""

import logging
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class StorageService:
    """
    Thin wrapper around boto3 pointing at an S3-compatible endpoint (CESNET e-INFRA).
    """

    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
            ),
            region_name=settings.s3_region,
        )
        self._check_buckets()

    def _check_buckets(self):
        """Verify that the required buckets exist and are accessible. Raises on failure."""
        for bucket in [settings.s3_bucket_evidence, settings.s3_bucket_docs]:
            try:
                self.client.head_bucket(Bucket=bucket)
                logger.debug("S3 bucket accessible", extra={"event": "s3_bucket_ok", "bucket": bucket})
            except ClientError as e:
                code = e.response["Error"]["Code"]
                if code in ("403", "AccessDenied"):
                    logger.error(
                        "S3 bucket exists but credentials are rejected — check S3_ACCESS_KEY/S3_SECRET_KEY",
                        extra={"event": "s3_bucket_auth_error", "bucket": bucket, "code": code},
                    )
                elif code in ("404", "NoSuchBucket"):
                    logger.error(
                        "S3 bucket does not exist — create it with Terraform (infra/terraform/metacentrum-s3)",
                        extra={"event": "s3_bucket_missing", "bucket": bucket},
                    )
                else:
                    logger.error(
                        "S3 bucket check failed: %s", e,
                        extra={"event": "s3_bucket_error", "bucket": bucket, "code": code},
                    )
                raise RuntimeError(f"S3 bucket '{bucket}' is not accessible (code={code})") from e

    def upload(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload bytes to S3.

        Args:
            bucket: Which bucket to store in
            key: The filename/path within the bucket
            data: The raw bytes to store
            content_type: MIME type (image/png, text/html, etc.)

        Returns:
            The storage key (use this to retrieve the file later)
        """
        self.client.put_object(
            Bucket=bucket,
            Key=key,
            Body=BytesIO(data),
            ContentType=content_type,
        )
        logger.debug(f"Uploaded {len(data)} bytes to {bucket}/{key}")
        return key

    def download(self, bucket: str, key: str) -> bytes:
        """Download a file from S3 and return as bytes."""
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def get_presigned_url(self, bucket: str, key: str, expires_seconds: int = 3600) -> str:
        """
        Generate a temporary URL to access a file directly.
        Useful for showing screenshots in the UI without proxying through the API.
        """
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def delete(self, bucket: str, key: str):
        """Delete a file from storage."""
        self.client.delete_object(Bucket=bucket, Key=key)

    def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        """List all file keys in a bucket with optional prefix filter."""
        response = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [obj["Key"] for obj in response.get("Contents", [])]
