"""roles, restrictions, audit, secure sessions and encrypted tokens

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("role", sa.String(length=20), nullable=False, server_default="user"),
    )
    op.create_check_constraint(
        "ck_users_role",
        "users",
        "role IN ('owner', 'streamer', 'admin', 'editor', 'user')",
    )
    op.create_index("ix_users_role", "users", ["role"])

    op.create_table(
        "user_restrictions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("lifted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('twitch_ban', 'service_ban')",
            name="ck_user_restrictions_kind",
        ),
        sa.CheckConstraint(
            "source IN ('twitch_api', 'manual')",
            name="ck_user_restrictions_source",
        ),
    )
    op.create_index(
        "ix_user_restrictions_user_id", "user_restrictions", ["user_id"]
    )
    op.create_index(
        "ux_user_restrictions_active",
        "user_restrictions",
        ["user_id", "kind", sa.text("COALESCE(channel, '')")],
        unique=True,
        postgresql_where=sa.text("lifted_at IS NULL"),
    )

    op.create_table(
        "moderation_audit",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "target_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("ip", sa.Text(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_moderation_audit_actor_user_id", "moderation_audit", ["actor_user_id"]
    )
    op.create_index(
        "ix_moderation_audit_target_user_id", "moderation_audit", ["target_user_id"]
    )

    # Old sessions use an unhashed session id. There is no production deployment
    # yet, so invalidate them instead of inventing a migration path.
    op.execute("DELETE FROM web_sessions")
    op.add_column("web_sessions", sa.Column("token_hash", sa.String(length=64)))
    op.add_column("web_sessions", sa.Column("csrf_hash", sa.String(length=64)))
    op.add_column(
        "web_sessions", sa.Column("absolute_expires_at", sa.DateTime(), nullable=True)
    )
    op.alter_column("web_sessions", "token_hash", nullable=False)
    op.alter_column("web_sessions", "csrf_hash", nullable=False)
    op.create_index(
        "ux_web_sessions_token_hash", "web_sessions", ["token_hash"], unique=True
    )

    for table in ("twitch_authorizations", "twitch_streamer_authorizations"):
        op.add_column(table, sa.Column("access_token_encrypted", sa.Text()))
        op.add_column(table, sa.Column("refresh_token_encrypted", sa.Text()))
        op.add_column(
            table,
            sa.Column(
                "key_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )
        op.alter_column(table, "access_token", nullable=True)
        op.alter_column(table, "refresh_token", nullable=True)


def downgrade() -> None:
    for table in ("twitch_authorizations", "twitch_streamer_authorizations"):
        op.alter_column(table, "access_token", nullable=False)
        op.alter_column(table, "refresh_token", nullable=False)
        op.drop_column(table, "key_version")
        op.drop_column(table, "refresh_token_encrypted")
        op.drop_column(table, "access_token_encrypted")

    op.drop_index("ux_web_sessions_token_hash", table_name="web_sessions")
    op.drop_column("web_sessions", "absolute_expires_at")
    op.drop_column("web_sessions", "csrf_hash")
    op.drop_column("web_sessions", "token_hash")

    op.drop_index("ix_moderation_audit_target_user_id", table_name="moderation_audit")
    op.drop_index("ix_moderation_audit_actor_user_id", table_name="moderation_audit")
    op.drop_table("moderation_audit")

    op.drop_index("ux_user_restrictions_active", table_name="user_restrictions")
    op.drop_index("ix_user_restrictions_user_id", table_name="user_restrictions")
    op.drop_table("user_restrictions")

    op.drop_index("ix_users_role", table_name="users")
    op.drop_constraint("ck_users_role", "users", type_="check")
    op.drop_column("users", "role")
