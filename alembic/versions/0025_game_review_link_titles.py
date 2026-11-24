"""Store a display title with each game review link.

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE games AS game
        SET review_links = COALESCE(
            (
                SELECT jsonb_agg(
                    CASE
                        WHEN jsonb_typeof(entry.value) = 'object' THEN entry.value
                        ELSE jsonb_build_object(
                            'title',
                            CASE
                                WHEN lower(entry.value #>> '{}') LIKE 'https://t.me/%'
                                  OR lower(entry.value #>> '{}') LIKE 'https://telegram.me/%'
                                  OR lower(entry.value #>> '{}') LIKE 'https://www.telegram.me/%'
                                    THEN 'Telegram'
                                WHEN lower(entry.value #>> '{}') LIKE 'https://twitch.tv/%'
                                  OR lower(entry.value #>> '{}') LIKE 'https://www.twitch.tv/%'
                                  OR lower(entry.value #>> '{}') LIKE 'https://clips.twitch.tv/%'
                                    THEN 'Twitch'
                                WHEN lower(entry.value #>> '{}') LIKE 'https://youtube.com/%'
                                  OR lower(entry.value #>> '{}') LIKE 'https://www.youtube.com/%'
                                  OR lower(entry.value #>> '{}') LIKE 'https://youtu.be/%'
                                    THEN 'YouTube'
                                ELSE 'Ссылка'
                            END,
                            'url',
                            entry.value #>> '{}'
                        )
                    END
                    ORDER BY entry.ordinality
                )
                FROM jsonb_array_elements(game.review_links)
                    WITH ORDINALITY AS entry(value, ordinality)
            ),
            '[]'::jsonb
        )
        WHERE jsonb_typeof(game.review_links) = 'array'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE games AS game
        SET review_links = COALESCE(
            (
                SELECT jsonb_agg(
                    CASE
                        WHEN jsonb_typeof(entry.value) = 'object'
                            THEN entry.value -> 'url'
                        ELSE entry.value
                    END
                    ORDER BY entry.ordinality
                )
                FROM jsonb_array_elements(game.review_links)
                    WITH ORDINALITY AS entry(value, ordinality)
            ),
            '[]'::jsonb
        )
        WHERE jsonb_typeof(game.review_links) = 'array'
        """
    )
