"""Baseline schema

Revision: 0001
Previous: None
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), unique=True, nullable=False, index=True),
        sa.Column("hashed_password", sa.String(), nullable=True),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("role", sa.Enum("admin", "curator", "analyst", "user", name="userrole"), nullable=False, server_default="user"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("oauth_provider", sa.String(), nullable=True),
        sa.Column("oauth_id", sa.String(), nullable=True, index=True),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "sources",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("base_url", sa.String(), nullable=False),
        sa.Column("permission_type", sa.String(), nullable=False),
        sa.Column("permission_ref", sa.Text(), nullable=True),
        sa.Column("preferred_strategy", sa.Enum("api", "html", "rendered", "screenshot", "upstream_ai", name="ingeststrategy"), server_default="html"),
        sa.Column("crawl_frequency_hours", sa.Integer(), server_default="24"),
        sa.Column("crawl_depth", sa.Integer(), server_default="1"),
        sa.Column("rate_limit_rps", sa.Float(), server_default="1.0"),
        sa.Column("retention_days_evidence", sa.Integer(), server_default="90"),
        sa.Column("retention_days_index", sa.Integer(), server_default="365"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("last_crawled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "ingest_jobs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("strategy_used", sa.Enum("api", "html", "rendered", "screenshot", "upstream_ai", name="ingeststrategy"), nullable=True),
        sa.Column("status", sa.Enum("pending", "running", "done", "failed", "captcha_blocked", name="jobstatus"), server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("job_id", sa.String(), sa.ForeignKey("ingest_jobs.id"), nullable=False),
        sa.Column("type", sa.Enum("screenshot", "html", "dom", "pdf", name="evidencetype"), nullable=False),
        sa.Column("storage_uri", sa.String(), nullable=False),
        sa.Column("file_hash", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source_id", sa.String(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("doc_version", sa.Integer(), server_default="1"),
        sa.Column("content_uri", sa.String(), nullable=True),
        sa.Column("quality_score", sa.Float(), nullable=True),
        sa.Column("ingest_strategy", sa.Enum("api", "html", "rendered", "screenshot", "upstream_ai", name="ingeststrategy"), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("document_id", sa.String(), sa.ForeignKey("documents.id"), nullable=False),
        sa.Column("chunk_type", sa.Enum("text", "table", "block", name="chunktype"), server_default="text"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("citation_url", sa.String(), nullable=True),
        sa.Column("citation_evidence_id", sa.String(), sa.ForeignKey("evidence.id"), nullable=True),
        sa.Column("bounding_box", sa.JSON(), nullable=True),
        sa.Column("is_embedded", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("type", sa.Enum("captcha", "rate_limited", "blocked", name="incidenttype"), server_default="captcha"),
        sa.Column("source_id", sa.String(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("strategy", sa.Enum("api", "html", "rendered", "screenshot", "upstream_ai", name="ingeststrategy"), nullable=True),
        sa.Column("severity", sa.String(), server_default="medium"),
        sa.Column("status", sa.Enum("open", "in_progress", "resolved", name="incidentstatus"), server_default="open"),
        sa.Column("detector", sa.String(), nullable=True),
        sa.Column("evidence_screenshot_uri", sa.String(), nullable=True),
        sa.Column("resolved_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("object_type", sa.String(), nullable=True),
        sa.Column("object_id", sa.String(), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("incidents")
    op.drop_table("chunks")
    op.drop_table("documents")
    op.drop_table("evidence")
    op.drop_table("ingest_jobs")
    op.drop_table("sources")
    op.drop_table("users")
    for enum_name in ("userrole", "ingeststrategy", "jobstatus", "evidencetype", "chunktype", "incidenttype", "incidentstatus"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
