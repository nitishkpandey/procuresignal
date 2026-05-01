"""Initial schema with 7 tables

Revision ID: 9739a6693138
Revises:
Create Date: 2026-05-01 11:17:50.692768

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "9739a6693138"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
