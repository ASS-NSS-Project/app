"""
services/storage_service.py - File Storage (MinIO)

MinIO is a local S3-compatible object storage.
Think of it like a self-hosted Google Drive for our evidence files.

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
    Thin wrapper around boto3 (AWS S3 SDK) pointing at our local MinIO.
    """

    def __init__(self):
        # boto3 is the AWS Python SDK.
        # By pointing endpoint_url at MinIO, it works identically.
        self.client = boto3.client(
            "s3",
            endpoint_url=f"http://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_root_user,
            aws_secret_access_key=settings.minio_root_password,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",  # MinIO requires a region name (any value works)
        )
        self._ensure_buckets()

    def _ensure_buckets(self):
        """Create storage buckets if they don't exist yet."""
        for bucket in [settings.minio_bucket_evidence, settings.minio_bucket_docs]:
            try:
                self.client.head_bucket(Bucket=bucket)
            except ClientError:
                try:
                    self.client.create_bucket(Bucket=bucket)
                    logger.info(f"Created MinIO bucket: {bucket}")
                except Exception as e:
                    logger.warning(f"Could not create bucket {bucket}: {e}")

    def upload(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """
        Upload bytes to MinIO.
        
        Args:
            bucket: Which bucket (folder) to store in
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
        """Download a file from MinIO and return as bytes."""
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
