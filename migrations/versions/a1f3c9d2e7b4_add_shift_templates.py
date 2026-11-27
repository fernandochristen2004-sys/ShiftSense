"""add shift templates

Revision ID: a1f3c9d2e7b4
Revises: cfda9382ff12
Create Date: 2026-11-27 06:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1f3c9d2e7b4'
down_revision: Union[str, Sequence[str], None] = 'cfda9382ff12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('shift_templates',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=True), nullable=False),
    sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('shifts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('restaurant_id', 'name')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('shift_templates')
