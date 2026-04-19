"""Add new fields to chunks

Revision: 0004
Previous: 0003
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("parent_chunk_id", sa.String(), sa.ForeignKey("chunks.id"), nullable=True))
    op.add_column("chunks", sa.Column("section_path", sa.String(), nullable=True))
    op.add_column("chunks", sa.Column("token_count", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("source_method", sa.String(), nullable=True))
    op.add_column("chunks", sa.Column("language", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "language")
    op.drop_column("chunks", "source_method")
    op.drop_column("chunks", "token_count")
    op.drop_column("chunks", "section_path")
    op.drop_column("chunks", "parent_chunk_id")
