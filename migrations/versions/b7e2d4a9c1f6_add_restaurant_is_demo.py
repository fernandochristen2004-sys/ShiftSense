"""add restaurant is_demo

Revision ID: b7e2d4a9c1f6
Revises: a1f3c9d2e7b4
Create Date: 2026-11-27 19:20:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b7e2d4a9c1f6'
down_revision: Union[str, Sequence[str], None] = 'a1f3c9d2e7b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('restaurants', sa.Column(
        'is_demo', sa.Boolean(), server_default=sa.text('false'), nullable=False,
        comment='Sample data to try the app with',
    ))
    # Restaurants made by the demo seeder before this flag existed.
    op.execute("UPDATE restaurants SET is_demo = true WHERE name = 'Demo Bistro'")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('restaurants', 'is_demo')
