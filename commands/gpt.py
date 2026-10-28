import asyncio

from twitchio.ext import commands

from services.authz_service import Capability, resolve_actor
from services.command_registry import register_command
from services.gpt_service import ask_gpt
from utils.cooldowns import check_cooldown
from utils.delays import human_delay


def setup(bot):

    register_command(
        "gpt",
        "Команда: !gpt [вопрос] - задать вопрос нейронке",
        "mod"
    )

    @commands.command(name="gpt")
    async def gpt_command(ctx, *, question: str = None):

        actor = await resolve_actor(
            twitch_user_id=getattr(ctx.author, "id", None),
            login=ctx.author.name,
        )
        if not actor.can_command(Capability.ADMIN_COMMANDS):
            return

        if not question:    # проверяем есть ли тело вопроса
            await ctx.send("MrDestructoid Используй: !вопрос <текст>")
            return

        if len(question) > 200:    # проверяем длину вопроса
            await ctx.send("MrDestructoid Вопрос слишком длинный")
            return

        if "http://" in question or "https://" in question:    # проверяем, что нет ссылок
            await ctx.send("MrDestructoid Ссылки запрещены")
            return

        if not check_cooldown(ctx, "вопрос", 20):    # проверяем кулдаун
            return

        await human_delay()

        try:
            # Gemini, OpenRouter and g4f each have their own request timeout.
            # Keep the command deadline long enough for the fallback chain.
            answer = await asyncio.wait_for(ask_gpt(question), timeout=210)

            if not answer:
                await ctx.send("MrDestructoid Я не знаю ответа")
                return

            answer = answer.strip().replace("\n", " ")
            if len(answer) > 150:
                answer = answer[:147] + "..."

            await ctx.send(f"MrDestructoid {answer}")

        except Exception as e:
            print("gpt error:", e)
            await ctx.send("MrDestructoid GPT временно недоступен")

    bot.add_command(gpt_command)
