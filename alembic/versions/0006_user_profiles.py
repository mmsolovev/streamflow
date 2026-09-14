"""add user_profiles, move mutable user data out of users

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("login", sa.Text(), nullable=True),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("profile_image_url", sa.Text(), nullable=True),
        sa.Column("twitch_url", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("is_current", sa.Boolean(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"], unique=False)
    op.create_index("ix_user_profiles_login", "user_profiles", ["login"], unique=False)
    op.create_index(
        "ix_user_profiles_current_unique",
        "user_profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.execute("""
        INSERT INTO user_profiles
            (user_id, login, display_name, profile_image_url, twitch_url,
             first_seen_at, last_seen_at, is_current, updated_at)
        SELECT
            id,
            login,
            display_name,
            profile_image_url,
            twitch_url,
            created_at,
            COALESCE(last_seen_at, created_at),
            TRUE,
            COALESCE(last_seen_at, created_at)
        FROM users
        WHERE login IS NOT NULL OR display_name IS NOT NULL
    """)

    op.drop_column("users", "login")
    op.drop_column("users", "display_name")
    op.drop_column("users", "profile_image_url")
    op.drop_column("users", "twitch_url")
    op.drop_column("users", "last_seen_at")


def downgrade() -> None:
    op.add_column("users", sa.Column("login", sa.Text(), unique=True))
    op.add_column("users", sa.Column("display_name", sa.Text()))
    op.add_column("users", sa.Column("profile_image_url", sa.Text()))
    op.add_column("users", sa.Column("twitch_url", sa.Text()))
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime()))

    op.execute("""
        UPDATE users u
        SET login = up.login,
            display_name = up.display_name,
            profile_image_url = up.profile_image_url,
            twitch_url = up.twitch_url,
            last_seen_at = up.last_seen_at
        FROM user_profiles up
        WHERE up.user_id = u.id AND up.is_current = TRUE
    """)

    op.drop_index("ix_user_profiles_current_unique", table_name="user_profiles")
    op.drop_index("ix_user_profiles_login", table_name="user_profiles")
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_table("user_profiles")