"""Authentication, request-size, and rate-limit controls."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.runtime.config import Settings
from src.runtime.security import (
    RequestGuardMiddleware,
    SlidingWindowRateLimiter,
    require_api_token,
)


def test_sliding_window_expires_old_requests() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)
    assert limiter.allow("client", now=1)
    assert limiter.allow("client", now=2)
    assert not limiter.allow("client", now=3)
    assert limiter.allow("client", now=12)
    assert limiter.allow("other-client")


def _guarded_app(*, token: str | None = "secret") -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(_env_file=None, api_token=token)  # type: ignore[call-arg]
    app.add_middleware(
        RequestGuardMiddleware,
        max_body_bytes=16,
        rate_limit_requests=2,
        rate_limit_window_seconds=60,
    )

    @app.post("/api/test", dependencies=[Depends(require_api_token)])
    async def endpoint() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/unprotected")
    async def unprotected() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_bearer_auth_success_invalid_and_unconfigured() -> None:
    with TestClient(_guarded_app()) as client:
        assert (
            client.post("/api/test", headers={"Authorization": "Bearer secret"}).status_code == 200
        )
        assert (
            client.post("/api/test", headers={"Authorization": "Bearer wrong"}).status_code == 401
        )
    with TestClient(_guarded_app(token=None)) as client:
        assert client.post("/api/test").status_code == 503


def test_body_limit_rate_limit_and_unprotected_route() -> None:
    with TestClient(_guarded_app()) as client:
        headers = {"Authorization": "Bearer secret"}
        assert client.post("/api/test", content=b"x" * 17, headers=headers).status_code == 413
        assert client.post("/api/test", headers=headers).status_code == 200
        assert client.post("/api/test", headers=headers).status_code == 200
        assert client.post("/api/test", headers=headers).status_code == 429
        assert client.get("/unprotected").status_code == 200


def test_streamed_body_without_content_length_is_still_limited() -> None:
    with TestClient(_guarded_app()) as client:
        response = client.post(
            "/api/test",
            content=(chunk for chunk in (b"x" * 10, b"y" * 10)),
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 413


def test_invalid_content_length_is_rejected() -> None:
    app = _guarded_app()
    with TestClient(app) as client:
        response = client.post(
            "/api/test",
            content=b"",
            headers={"Authorization": "Bearer secret", "content-length": "invalid"},
        )
    assert response.status_code == 400
