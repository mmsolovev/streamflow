"""Web-layer settings: read from env with pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BackendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # CORS: comma-separated origins (frontend). Empty = no CORS headers.
    backend_cors_origins: list[str] = []

    # Cookie with the web session id.
    backend_cookie_name: str = "backend_session_id"
    backend_cookie_secure: bool = False
    backend_session_ttl_days: int = 30
    backend_session_cleanup_interval_seconds: int = 3600

    # uvicorn defaults for `backend.main:app`.
    backend_host: str = "127.0.0.1"
    backend_port: int = 8001

    # Twitch OAuth. Existing CLIENT_ID/CLIENT_SECRET values are accepted too.
    twitch_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TWITCH_CLIENT_ID", "CLIENT_ID"),
    )
    twitch_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TWITCH_CLIENT_SECRET", "CLIENT_SECRET"),
    )
    twitch_redirect_uri: str | None = None
    twitch_scope: str = "user:read:email"

    # Scopes for the streamer "elevated" OAuth flow (/auth/streamer/*).
    # Space-separated (Twitch wants a space-delimited list). Используется
    # только для аккаунтов из STREAMER_LOGINS (config/settings.py). Меняй здесь
    # или в .env (TWITCH_STREAMER_SCOPE), чтобы выбрать доп. права.
    # Кандидаты для функционала канала:
    #   channel:read:redemptions, channel:manage:redemptions
    #   channel:read:subscriptions, channel:read:polls, channel:manage:polls
    #   channel:read:predictions, channel:manage:predictions
    #   channel:read:goals, channel:read:hype_train, channel:manage:broadcast
    #   moderator:read:chatters, moderator:manage:banned_users
    twitch_streamer_scope: str = "channel:read:redemptions channel:manage:redemptions"

    twitch_oauth_state_ttl_seconds: int = 600
    twitch_token_refresh_skew_seconds: int = 300
    backend_oauth_state_cookie_name: str = "backend_oauth_state"
    backend_csrf_cookie_name: str = "backend_csrf_token"

    # Frontend base URL. When set, a successful /auth/callback redirects the
    # browser here (with `?login=success`) instead of returning JSON, so the SPA
    # can render the logged-in state. Empty = JSON response.
    backend_frontend_url: str | None = None

    # Streamer whose manual columns are edited by the web layer.
    # Mirrors SHEETS_STREAMER_ID from config/settings.py.
    backend_streamer_id: int | None = None

    # API prefix (not used by routers directly, kept for docs/CLI).
    backend_api_prefix: str = "/api/v1"

    @property
    def twitch_streamer_scopes(self) -> list[str]:
        """`twitch_streamer_scope` как список (переносит и запятые, и пробелы)."""
        return [
            scope
            for scope in self.twitch_streamer_scope.replace(",", " ").split()
            if scope
        ]


@lru_cache
def get_backend_settings() -> BackendSettings:
    return BackendSettings()
