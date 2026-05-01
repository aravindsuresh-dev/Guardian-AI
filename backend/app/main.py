"""Guardian AI — FastAPI entrypoint."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import router
from app.config import settings


def create_app() -> FastAPI:
    s = settings()
    app = FastAPI(
        title="Guardian AI",
        description="Multi-agent adversarial compliance engine for telecom marketing content.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "app": "Guardian AI"}

    return app


app = create_app()
