"""add telegram_announcements.custom_emoji_id

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-01

Summary:
Колонка для кастомного эмодзи из набора стикеров, который стример ставит
в подпись ссылки на канал в анонсе. Бот читает emoji_id из entities этого
поста и переиспользует его в подписи на запись — так оформление совпадает
с ручной правкой стримера.

Тип String, а не BigInteger: Bot API отдаёт custom_emoji_id строкой
(это же значение подставляется в tg://emoji?id=...), и приводить его к
числу означало бы потерять формат значения при обратной подстановке.

Nullable: у постов без кастомного эмодзи и у обычных Unicode-эмодзи
значения нет, и тогда подпись собирается на Unicode-символе.

Дополнительный индекс не нужен: значение только читается вместе с постом
по primary key, поиска по нему не будет.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "telegram_announcements",
        sa.Column("custom_emoji_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("telegram_announcements", "custom_emoji_id")
