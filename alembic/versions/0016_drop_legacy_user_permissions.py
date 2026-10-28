"""drop legacy user permission flags

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("users", "is_trusted")
    op.drop_column("users", "twitch_management")
    op.drop_column("users", "is_admin")


def downgrade() -> None:
    op.add_column("users", sa.Column("is_admin", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    op.add_column("users", sa.Column("twitch_management", sa.Boolean(), nullable=True, server_default=sa.text("false")))
    op.add_column("users", sa.Column("is_trusted", sa.Boolean(), nullable=True, server_default=sa.text("false")))
