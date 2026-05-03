"""
services/storage_service.py - File Storage (S3-compatible object storage)

Uses CESNET S3 (e-INFRA) in production via boto3.
Configuration is driven entirely from environment variables (S3_* in .env).

We store:
- Screenshots (.png)
- Raw HTML dumps (.html)
- PDF evidence (.pdf)
- Structured document JSON (.json)
- Processed markdown (.md)
- Chunks metadata (chunks.json)
- Embedding backups (.npy, .npz)

Files are organized by: source_id / job_id / filename
"""

import json
import logging
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
import numpy as np

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

    def store_document_bundle(
        self,
        source_id: str,
        job_id: str,
        markdown: str,
        chunks: list[dict],
        metadata: dict
    ) -> tuple[str, str, str]:
        """
        Store complete document bundle to S3 for resilient storage.

        Args:
            source_id: Source UUID
            job_id: IngestJob UUID
            markdown: Processed markdown content
            chunks: List of chunk dictionaries (serializable)
            metadata: Job metadata (strategy, quality_score, timestamps)

        Returns:
            Tuple of (markdown_uri, chunks_uri, metadata_uri)
        """
        base_key = f"{source_id}/{job_id}"

        # Upload markdown
        markdown_key = f"{base_key}/document.md"
        self.upload(
            bucket=settings.s3_bucket_docs,
            key=markdown_key,
            data=markdown.encode('utf-8'),
            content_type="text/markdown"
        )
        markdown_uri = f"s3://{settings.s3_bucket_docs}/{markdown_key}"

        # Upload chunks JSON
        chunks_key = f"{base_key}/chunks.json"
        chunks_json = json.dumps(chunks, indent=2, ensure_ascii=False)
        self.upload(
            bucket=settings.s3_bucket_docs,
            key=chunks_key,
            data=chunks_json.encode('utf-8'),
            content_type="application/json"
        )
        chunks_uri = f"s3://{settings.s3_bucket_docs}/{chunks_key}"

        # Upload metadata
        metadata_key = f"{base_key}/metadata.json"
        metadata_json = json.dumps(metadata, indent=2, ensure_ascii=False)
        self.upload(
            bucket=settings.s3_bucket_docs,
            key=metadata_key,
            data=metadata_json.encode('utf-8'),
            content_type="application/json"
        )
        metadata_uri = f"s3://{settings.s3_bucket_docs}/{metadata_key}"

        logger.info(
            "Stored document bundle to S3",
            extra={
                "event": "document_bundle_stored",
                "source_id": source_id,
                "job_id": job_id,
                "chunk_count": len(chunks),
                "markdown_size": len(markdown)
            }
        )

        return markdown_uri, chunks_uri, metadata_uri

    def load_chunks_from_s3(self, chunks_uri: str) -> list[dict]:
        """
        Load chunks.json from S3.

        Args:
            chunks_uri: Full S3 URI (s3://bucket/path/to/chunks.json)

        Returns:
            List of chunk dictionaries
        """
        # Parse S3 URI
        if not chunks_uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {chunks_uri}")

        parts = chunks_uri[5:].split("/", 1)
        bucket = parts[0]
        key = parts[1]

        # Download and parse JSON
        data = self.download(bucket, key)
        chunks = json.loads(data.decode('utf-8'))

        logger.debug(
            "Loaded chunks from S3",
            extra={
                "event": "chunks_loaded_from_s3",
                "chunks_uri": chunks_uri,
                "chunk_count": len(chunks)
            }
        )

        return chunks

    def store_embedding_backup(
        self,
        chunk_id: str,
        dense_vector: np.ndarray,
        sparse_indices: list[int],
        sparse_values: list[float]
    ) -> str:
        """
        Optional: backup embedding vectors to S3 for disaster recovery.

        Args:
            chunk_id: Chunk UUID
            dense_vector: NumPy array of dense embeddings (1024 floats)
            sparse_indices: Sparse vector indices
            sparse_values: Sparse vector values

        Returns:
            S3 URI where embeddings are stored
        """
        if not settings.enable_embedding_backup_s3:
            return ""

        base_key = f"{chunk_id}"

        # Store dense vector as .npy
        dense_key = f"{base_key}/dense.npy"
        dense_bytes = BytesIO()
        np.save(dense_bytes, dense_vector, allow_pickle=False)
        self.upload(
            bucket=settings.s3_bucket_embeddings,
            key=dense_key,
            data=dense_bytes.getvalue(),
            content_type="application/octet-stream"
        )

        # Store sparse as .npz (compressed)
        sparse_key = f"{base_key}/sparse.npz"
        sparse_bytes = BytesIO()
        np.savez_compressed(
            sparse_bytes,
            indices=np.array(sparse_indices, dtype=np.int32),
            values=np.array(sparse_values, dtype=np.float32)
        )
        self.upload(
            bucket=settings.s3_bucket_embeddings,
            key=sparse_key,
            data=sparse_bytes.getvalue(),
            content_type="application/octet-stream"
        )

        embedding_uri = f"s3://{settings.s3_bucket_embeddings}/{base_key}"
        logger.debug(
            "Backed up embedding to S3",
            extra={
                "event": "embedding_backed_up",
                "chunk_id": chunk_id,
                "embedding_uri": embedding_uri
            }
        )

        return embedding_uri
