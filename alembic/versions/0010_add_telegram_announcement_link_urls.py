"""add telegram_announcements.link_urls

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-02

Summary:
Колонка с адресами ссылок, которые Telegram прислал в entities поста.

Зачем. Стример пишет ссылку на канал скрытой подписью («💬TWITCH~»), а адрес
лежит в сущности `text_link`. В тексте поста URL нет вообще, поэтому разбор
текста его не находил: анонс не проходил проверку ссылки на канал, поток
заканчивался, и в пост не попадала ссылка на запись.

Без этой колонки восстановить адрес позже нельзя — апдейт с entities
одноразовый, и текста самого поста недостаточно.

Хранится JSON-массивом строк в порядке появления ссылок: порядок важен
диагностике, а массив целиком влезает в Text дешевле, чем вторая таблица.

Nullable: у постов без ссылок (обычные новости, репосты) значения нет, и
разбор должен это переживать, а не падать.

Дополнительный индекс не нужен: колонка читается только вместе с постом,
поиска по ней не будет.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_announcements",
        sa.Column("link_urls", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_announcements", "link_urls")