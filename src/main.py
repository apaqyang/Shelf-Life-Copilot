"""Shelf-Life Copilot FastAPI application entry point.

Starting `uvicorn src.main:app` brings up the full v0.1 service:
- DailyScheduler 07:00 (if LLM key configured)
- MonthlyReportScheduler day 1 08:00 Asia/Shanghai
- POST /webhook/wecom for click callbacks
- GET /health for liveness probes
"""

from __future__ import annotations

from fastapi import FastAPI

from src.runtime import get_settings
from src.runtime.lifespan import build_lifespan
from src.webhook import router as wecom_webhook_router

app = FastAPI(
    title="Shelf-Life Copilot",
    description="食品行业临期 / 保质期管理 AI 副驾",
    version="0.1.0",
    lifespan=build_lifespan(get_settings()),
)

app.include_router(wecom_webhook_router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe used by container orchestrators and CI."""
    return {"status": "ok"}
