"""ASGI application factory: CORS, exception handlers, routers."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.config import get_backend_settings
from backend.routers import auth, games, health, hltb, meta, recommendations, releases, streams, users
from backend.security.maintenance import cleanup_expired_sessions_loop


def _error_body(code: str, message: Any) -> dict:
    return {"detail": {"code": code, "message": message}}


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def _handle_http_exception(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content={"detail": detail})
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body("error", detail),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content=_error_body("validation_error", exc.errors()),
        )


def create_app() -> FastAPI:
    settings = get_backend_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cleanup_task = asyncio.create_task(cleanup_expired_sessions_loop())
        try:
            yield
        finally:
            cleanup_task.cancel()
            await asyncio.gather(cleanup_task, return_exceptions=True)

    app = FastAPI(
        title="streamflow API",
        version="0.1.0",
        description="Web backend for the streamflow project (replaces Google Sheets as UI).",
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    if settings.backend_cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.backend_cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _register_exception_handlers(app)

    prefix = settings.backend_api_prefix.rstrip("/")
    app.include_router(health.router, prefix=prefix)
    app.include_router(games.router, prefix=prefix)
    app.include_router(hltb.router, prefix=prefix)
    app.include_router(streams.router, prefix=prefix)
    app.include_router(releases.router, prefix=prefix)
    app.include_router(recommendations.router, prefix=prefix)
    app.include_router(meta.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(users.router, prefix=prefix)

    return app


app = create_app()
