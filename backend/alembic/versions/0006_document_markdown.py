"""Add content_markdown column to documents

Revision: 0006
Previous: 0005
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("content_markdown", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("documents", "content_markdown")
