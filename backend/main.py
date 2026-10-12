"""uvicorn entrypoint: uvicorn backend.main:app"""
from __future__ import annotations

from backend.config import get_backend_settings
from backend.app import app  # noqa: F401  (re-exported for uvicorn)

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    settings = get_backend_settings()
    uvicorn.run("backend.main:app", host=settings.backend_host, port=settings.backend_port, reload=False)