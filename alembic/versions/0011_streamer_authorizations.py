"""add twitch_streamer_authorizations

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-16

Summary:
Отдельная таблица под «стримерский» OAuth-токен с расширенными scopes.

Зачем. Обычный веб-логин пишет токен в `twitch_authorizations` с ключом
user_id и перезаписывает его при каждом входе. Стримерский токен нужен с
другими scopes (например, баллы канала) и не должен затираться обычным
входом, поэтому живёт в своей таблице.

Ключ user_id, один токен на аккаунт. twitch_login хранится рядом, чтобы
админ-страница могла показать, какой аккаунт подключён, без join.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "twitch_streamer_authorizations",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("twitch_login", sa.Text(), nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column("refresh_token", sa.Text(), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("twitch_streamer_authorizations")
