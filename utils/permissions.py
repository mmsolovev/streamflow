from services.authz_service import Role, resolve_actor


async def is_allowed(user: str, twitch_user_id: str | None = None) -> bool:
    actor = await resolve_actor(twitch_user_id=twitch_user_id, login=user)
    return actor.role in {Role.OWNER, Role.STREAMER, Role.ADMIN, Role.EDITOR}
