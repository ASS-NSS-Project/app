"""Add generated_answer to experiment_queries

Revision: 0008
Previous: 0007
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("experiment_queries", sa.Column("generated_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("experiment_queries", "generated_answer")
