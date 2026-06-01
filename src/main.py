"""Shelf-Life Copilot FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI

from src.webhook import router as wecom_webhook_router

app = FastAPI(
    title="Shelf-Life Copilot",
    description="食品行业临期 / 保质期管理 AI 副驾",
    version="0.1.0",
)

app.include_router(wecom_webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by container orchestrators and CI."""
    return {"status": "ok"}
