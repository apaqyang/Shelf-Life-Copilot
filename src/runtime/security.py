"""Authentication, request-size, and in-process rate-limit controls."""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from threading import Lock

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from src.runtime.config import Settings


class SlidingWindowRateLimiter:
    def __init__(self, *, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        cutoff = current - self._window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self._limit:
                return False
            events.append(current)
            return True


class RequestGuardMiddleware(BaseHTTPMiddleware):
    """Limit request bodies and request rate on mutation endpoints."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        rate_limit_requests: int,
        rate_limit_window_seconds: int,
    ) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes
        self._limiter = SlidingWindowRateLimiter(
            limit=rate_limit_requests,
            window_seconds=rate_limit_window_seconds,
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        protected = request.method == "POST" and (
            request.url.path == "/webhook/wecom" or request.url.path.startswith("/api/")
        )
        if not protected:
            return await call_next(request)

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "invalid content-length"})
            if declared_length > self._max_body_bytes:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
        body = await request.body()
        if len(body) > self._max_body_bytes:
            return JSONResponse(status_code=413, content={"detail": "request body too large"})

        client = request.client.host if request.client is not None else "unknown"
        if not self._limiter.allow(f"{client}:{request.url.path}"):
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        return await call_next(request)


def require_api_token(request: Request) -> None:
    settings: Settings = request.app.state.settings
    if settings.api_token is None:
        raise HTTPException(status_code=503, detail="API token is not configured")
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    expected = settings.api_token.get_secret_value()
    if scheme.casefold() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")
