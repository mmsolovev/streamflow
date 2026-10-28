"""add restore-original command flag

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_announcement_vods",
        sa.Column("restore_requested_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_announcement_vods", "restore_requested_at")
