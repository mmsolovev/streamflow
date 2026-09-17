from twitchio.ext import commands

from config.settings import ADMINS
from services.command_registry import register_command
from services.lost_movie_service import (
    clear_movie,
    clear_movie_time,
    format_movie_for_chat,
    set_movie,
    set_movie_started_time,
)
from utils.cooldowns import check_cooldown
from utils.delays import human_delay


ALIASES = [
    "сериал",
    "серия",
    "кино",
    "film",
    "movie",
    "начало",
    "сезон",
    "lost",
    "лост"
]


def _is_admin(ctx) -> bool:
    return bool(ctx.author) and ctx.author.name in ADMINS


def setup(bot):
    register_command(
        "фильм",
        "Команда: !фильм — текущий фильм. Для админов: !фильм + <название> — установить фильм, "
        "!фильм - — сбросить, !фильм time — задать время начала, "
        "!фильм time <ЧЧ:ММ> — указанное время, !фильм - time — убрать время. ",
        "all",
        aliases=ALIASES,
    )

    @commands.command(name="фильм", aliases=ALIASES)
    async def movie_command(ctx, *args):
        if args and args[0] == "+":
            if not _is_admin(ctx):
                return

            title = " ".join(args[1:]).strip()
            if not title:
                await ctx.send("Дайте название фильма после «+»")
                return

            started_at = set_movie(title)
            await human_delay()
            await ctx.send(f"Фильм {title} | Начали в {started_at}")
            return

        if args and args[0] == "-":
            if not _is_admin(ctx):
                return

            if len(args) >= 2 and str(args[1]).casefold() == "time":
                clear_movie_time()
                await human_delay()
                await ctx.send("Время начала просмотра сброшено")
                return

            clear_movie()
            await human_delay()
            await ctx.send("Фильм сброшен")
            return

        if args and str(args[0]).casefold() == "time":
            if not _is_admin(ctx):
                return

            value = str(args[1]) if len(args) >= 2 else None
            result = set_movie_started_time(value)
            await human_delay()
            if result is None:
                await ctx.send("Формат времени: ЧЧ:ММ (например 13:47)")
                return
            await ctx.send(f"Время начала просмотра: {result}")
            return

        if not check_cooldown(ctx, "фильм", 20):
            return

        await human_delay()
        text = format_movie_for_chat()
        if not text:
            await ctx.send("Фильм не установлен")
            return
        await ctx.send(text)

    bot.add_command(movie_command)