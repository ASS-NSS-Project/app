"""Add rq_job_id to ingest_jobs

Revision: 0003
Previous: 0002
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ingest_jobs",
        sa.Column("rq_job_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ingest_jobs", "rq_job_id")
