"""encrypt and drop legacy plaintext Twitch token columns

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import os
import sqlalchemy as sa


CIPHER_PREFIX = "v1:"


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLES = ("twitch_authorizations", "twitch_streamer_authorizations")


def upgrade() -> None:
    # Revision 0014 added encrypted columns alongside the legacy values.  Do
    # the copy inside this migration so `alembic upgrade head` never silently
    # discards existing OAuth credentials.
    from cryptography.fernet import Fernet

    key = (os.getenv("TOKEN_ENCRYPTION_KEY") or "").strip()
    for table in TABLES:
        connection = op.get_bind()
        rows = connection.execute(
            sa.text(
                f"SELECT user_id, access_token, refresh_token, access_token_encrypted, refresh_token_encrypted FROM {table}"
            )
        ).mappings().all()
        needs_encryption = any(
            (row["access_token"] and not row["access_token_encrypted"])
            or (row["refresh_token"] and not row["refresh_token_encrypted"])
            for row in rows
        )
        if needs_encryption and not key:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required to migrate Twitch tokens")
        cipher = Fernet(key.encode()) if needs_encryption else None
        for row in rows:
            access = row["access_token_encrypted"] or (
                CIPHER_PREFIX + cipher.encrypt(row["access_token"].encode()).decode()
                if row["access_token"]
                else None
            )
            refresh = row["refresh_token_encrypted"] or (
                CIPHER_PREFIX + cipher.encrypt(row["refresh_token"].encode()).decode()
                if row["refresh_token"]
                else None
            )
            if access != row["access_token_encrypted"] or refresh != row["refresh_token_encrypted"]:
                connection.execute(
                    sa.text(
                        f"UPDATE {table} SET access_token_encrypted = :access, refresh_token_encrypted = :refresh, key_version = 1 WHERE user_id = :user_id"
                    ),
                    {"access": access, "refresh": refresh, "user_id": row["user_id"]},
                )
        op.drop_column(table, "access_token")
        op.drop_column(table, "refresh_token")


def downgrade() -> None:
    import sqlalchemy as sa

    for table in TABLES:
        op.add_column(table, sa.Column("access_token", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("refresh_token", sa.Text(), nullable=True))
