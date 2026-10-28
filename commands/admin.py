from twitchio.ext import commands

import services.runtime as runtime
from services.authz_service import Capability, resolve_actor
from services.command_registry import register_command


async def has_access(ctx):
    actor = await resolve_actor(
        twitch_user_id=getattr(ctx.author, "id", None),
        login=ctx.author.name,
    )
    return actor.can_command(Capability.ADMIN_COMMANDS)


def setup(bot):

    register_command("отбой", "Команда: !отбой Выключить бота", "mod")
    register_command("старт", "Команда: !старт Включить бота", "mod")

    @commands.command(name="отбой")
    async def stop_bot(ctx):
        if not await has_access(ctx):
            return

        if not runtime.BOT_ENABLED:
            await ctx.send("Бот уже выключен Deadge")
            return

        runtime.BOT_ENABLED = False
        await ctx.send("Бот ушёл спать Deadge")

    @commands.command(name="старт")
    async def start_bot(ctx):
        if not await has_access(ctx):
            return

        if runtime.BOT_ENABLED:
            await ctx.send("Бот уже работает veryCat")
            return

        runtime.BOT_ENABLED = True
        await ctx.send("Бот снова в деле Wokege")

    bot.add_command(stop_bot)
    bot.add_command(start_bot)
