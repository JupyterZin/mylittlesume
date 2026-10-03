"""inscrições Web Push do app

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = '0002'
down_revision: str | None = '0001'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('push_subscriptions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('endpoint', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('p256dh', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('auth', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('user_agent', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
    sa.Column('last_ok_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('endpoint')
    )


def downgrade() -> None:
    op.drop_table('push_subscriptions')
