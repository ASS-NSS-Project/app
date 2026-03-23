"""${message}

Revize: ${up_revision}
Předchozí: ${down_revision | comma,n}
Vytvořeno: ${create_date}

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# Identifikátory revize
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    """Aplikuje změny schématu (přidání sloupců, tabulek, indexů)."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Vrátí změny zpět (pro rollback)."""
    ${downgrades if downgrades else "pass"}
