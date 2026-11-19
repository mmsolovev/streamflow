"""Remove the unused Telegram custom emoji id.

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Explicitly clear stored ids before dropping the legacy column.
    op.execute(
        sa.text(
            "UPDATE telegram_announcements SET custom_emoji_id = NULL "
            "WHERE custom_emoji_id IS NOT NULL"
        )
    )
    op.drop_column("telegram_announcements", "custom_emoji_id")


def downgrade() -> None:
    # Historical values were deliberately discarded and cannot be restored.
    op.add_column(
        "telegram_announcements",
        sa.Column("custom_emoji_id", sa.String(length=64), nullable=True),
    )
