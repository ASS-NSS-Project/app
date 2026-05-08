"""
services/storage.py - S3-Compatible Object Storage

Wraps boto3 to store and retrieve files from CESNET e-INFRA S3 (production)
or MinIO (local development). Configuration comes entirely from S3_* env vars.

What gets stored:
- Evidence: screenshots (.png), HTML dumps (.html), PDFs (.pdf)
- Documents: processed Markdown (.md), chunk JSON (.json)
- Embeddings: dense vectors (.npy), sparse vectors (.npz) — optional backup

File layout within each bucket:
    <source_id>/<job_id>/document.md
    <source_id>/<job_id>/chunks.json
    <source_id>/<job_id>/metadata.json

The StorageService is instantiated per-request (or per-job in the worker).
It verifies bucket accessibility on __init__ and raises immediately if credentials
or buckets are misconfigured — fail-fast is better than silent data loss.
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
    Thin wrapper around boto3 for S3-compatible object storage.

    Supports both path-style URLs (MinIO: http://minio:9000/bucket/key)
    and virtual-hosted-style URLs (CESNET: https://bucket.s3.endpoint/key).
    The style is controlled by the S3_USE_PATH_STYLE env var.
    """

    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                signature_version="s3v4",
                # "path" addressing: http://endpoint/bucket/key (MinIO)
                # "auto" addressing: http://bucket.endpoint/key (AWS, CESNET)
                s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
            ),
            region_name=settings.s3_region,
        )
        # Fail fast if buckets are unreachable — better than failing silently mid-ingest
        self._check_buckets()

    def _check_buckets(self):
        """
        Verify that the evidence and docs buckets exist and are accessible.

        Uses head_bucket (a lightweight metadata-only request) to check access.
        Provides actionable error messages for the two most common failure modes:
        - Wrong credentials (403)
        - Missing bucket (404) — needs to be created via Terraform
        """
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
        Upload raw bytes to S3.

        Args:
            bucket: Destination bucket name (e.g. settings.s3_bucket_evidence).
            key: Object key / path within the bucket (e.g. "source_id/job_id/screenshot.png").
            data: Raw bytes to upload.
            content_type: MIME type stored as S3 object metadata.

        Returns:
            The key — use this to retrieve the file later with download() or get_presigned_url().
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
        """
        Download a file from S3 and return its contents as bytes.

        Args:
            bucket: Source bucket name.
            key: Object key within the bucket.

        Returns:
            Raw file bytes.
        """
        response = self.client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def get_presigned_url(self, bucket: str, key: str, expires_seconds: int = 3600) -> str:
        """
        Generate a temporary pre-signed URL that gives direct access to a file.

        Used by the documents API to let the frontend display screenshots without
        proxying the image bytes through the API server.

        Args:
            bucket: Bucket where the file lives.
            key: Object key within the bucket.
            expires_seconds: How long the URL remains valid (default 1 hour).

        Returns:
            A signed HTTPS URL that grants GET access to the file until it expires.
        """
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def delete(self, bucket: str, key: str):
        """
        Delete a file from S3.

        Args:
            bucket: Bucket where the file lives.
            key: Object key to delete.
        """
        self.client.delete_object(Bucket=bucket, Key=key)

    def list_keys(self, bucket: str, prefix: str = "") -> list[str]:
        """
        List all object keys in a bucket, optionally filtered by prefix.

        Note: list_objects_v2 returns at most 1000 keys per call. For buckets
        with >1000 objects this will silently truncate — add pagination if needed.

        Args:
            bucket: Bucket to list.
            prefix: Optional path prefix filter (e.g. "source_id/").

        Returns:
            List of object key strings.
        """
        response = self.client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        return [obj["Key"] for obj in response.get("Contents", [])]

    def store_document_bundle(
        self,
        source_id: str,
        job_id: str,
        markdown: str,
        chunks: list[dict],
        metadata: dict,
    ) -> tuple[str, str, str]:
        """
        Upload the full document bundle (markdown + chunks + metadata) to S3.

        Called by the ingest pipeline after extraction succeeds. Provides a
        durable backup of the extracted content separate from the Postgres DB.

        Args:
            source_id: UUID of the source this document belongs to.
            job_id: UUID of the ingest job that produced this document.
            markdown: The extracted document content in Markdown format.
            chunks: List of chunk dicts (text, type, index, etc.) as plain dicts.
            metadata: Job metadata dict (strategy, quality_score, timestamps, etc.).

        Returns:
            Tuple of (markdown_uri, chunks_uri, metadata_uri) as "s3://bucket/key" strings.
        """
        base_key = f"{source_id}/{job_id}"

        # Upload the Markdown content
        markdown_key = f"{base_key}/document.md"
        self.upload(
            bucket=settings.s3_bucket_docs,
            key=markdown_key,
            data=markdown.encode('utf-8'),
            content_type="text/markdown",
        )
        markdown_uri = f"s3://{settings.s3_bucket_docs}/{markdown_key}"

        # Upload the chunks as JSON (for future re-embedding without re-scraping)
        chunks_key = f"{base_key}/chunks.json"
        self.upload(
            bucket=settings.s3_bucket_docs,
            key=chunks_key,
            data=json.dumps(chunks, indent=2, ensure_ascii=False).encode('utf-8'),
            content_type="application/json",
        )
        chunks_uri = f"s3://{settings.s3_bucket_docs}/{chunks_key}"

        # Upload metadata (strategy used, quality score, timestamps)
        metadata_key = f"{base_key}/metadata.json"
        self.upload(
            bucket=settings.s3_bucket_docs,
            key=metadata_key,
            data=json.dumps(metadata, indent=2, ensure_ascii=False).encode('utf-8'),
            content_type="application/json",
        )
        metadata_uri = f"s3://{settings.s3_bucket_docs}/{metadata_key}"

        logger.info("Stored document bundle to S3", extra={
            "event": "document_bundle_stored",
            "source_id": source_id,
            "job_id": job_id,
            "chunk_count": len(chunks),
            "markdown_size": len(markdown),
        })

        return markdown_uri, chunks_uri, metadata_uri

    def load_chunks_from_s3(self, chunks_uri: str) -> list[dict]:
        """
        Load and parse a chunks.json file from S3.

        Args:
            chunks_uri: Full S3 URI in the form "s3://bucket/path/to/chunks.json".

        Returns:
            List of chunk dicts as originally stored by store_document_bundle().

        Raises:
            ValueError: If the URI is not in the expected "s3://" format.
        """
        if not chunks_uri.startswith("s3://"):
            raise ValueError(f"Invalid S3 URI: {chunks_uri}")

        # Split "s3://bucket/path/key" into bucket and key
        parts = chunks_uri[5:].split("/", 1)
        bucket = parts[0]
        key    = parts[1]

        data   = self.download(bucket, key)
        chunks = json.loads(data.decode('utf-8'))

        logger.debug("Loaded chunks from S3", extra={
            "event": "chunks_loaded_from_s3",
            "chunks_uri": chunks_uri,
            "chunk_count": len(chunks),
        })
        return chunks

    def store_embedding_backup(
        self,
        chunk_id: str,
        dense_vector: np.ndarray,
        sparse_indices: list[int],
        sparse_values: list[float],
    ) -> str:
        """
        Optionally back up raw embedding vectors to S3 for disaster recovery.

        Only runs when ENABLE_EMBEDDING_BACKUP_S3=true. Storing all vectors for a
        large index would be expensive; this is disabled by default.

        Args:
            chunk_id: UUID of the chunk these embeddings belong to.
            dense_vector: NumPy array of 1024 float32 values (BGE-M3 dense output).
            sparse_indices: Sparse vector token indices (BM25-like lexical weights).
            sparse_values: Sparse vector weights corresponding to sparse_indices.

        Returns:
            S3 URI prefix where the vectors are stored, or empty string if backup is disabled.
        """
        if not settings.enable_embedding_backup_s3:
            return ""

        base_key = chunk_id

        # Dense vector as .npy (NumPy binary format — efficient and lossless)
        dense_key   = f"{base_key}/dense.npy"
        dense_bytes = BytesIO()
        np.save(dense_bytes, dense_vector, allow_pickle=False)
        self.upload(
            bucket=settings.s3_bucket_embeddings,
            key=dense_key,
            data=dense_bytes.getvalue(),
            content_type="application/octet-stream",
        )

        # Sparse vector as .npz (compressed NumPy archive with two arrays)
        sparse_key   = f"{base_key}/sparse.npz"
        sparse_bytes = BytesIO()
        np.savez_compressed(
            sparse_bytes,
            indices=np.array(sparse_indices, dtype=np.int32),
            values=np.array(sparse_values, dtype=np.float32),
        )
        self.upload(
            bucket=settings.s3_bucket_embeddings,
            key=sparse_key,
            data=sparse_bytes.getvalue(),
            content_type="application/octet-stream",
        )

        embedding_uri = f"s3://{settings.s3_bucket_embeddings}/{base_key}"
        logger.debug("Backed up embedding to S3", extra={
            "event": "embedding_backed_up",
            "chunk_id": chunk_id,
            "embedding_uri": embedding_uri,
        })
        return embedding_uri
