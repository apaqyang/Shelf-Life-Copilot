"""Authentication, request-size, and pluggable rate-limit controls."""

from __future__ import annotations

import hmac
import logging
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from importlib import import_module
from threading import Lock
from typing import Annotated, Any, Protocol, cast

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from src.observability import log_event, metrics
from src.runtime.config import Settings
from src.runtime.tenant import Principal, Role

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    """Request-rate boundary implemented locally or by shared persistence."""

    def allow(self, key: str, *, now: float | None = None) -> bool: ...  # pragma: no cover


class TokenVerifier(Protocol):
    def verify(self, token: str) -> dict[str, Any]: ...  # pragma: no cover


class OIDCJWTVerifier:
    """Validate asymmetric OIDC access tokens against a cached JWKS endpoint."""

    def __init__(self, *, jwks_url: str, issuer: str, audience: str) -> None:
        try:
            jwt = import_module("jwt")
        except ModuleNotFoundError as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError("OIDC mode requires the 'oidc' project extra") from exc
        self._jwt = jwt
        self._jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
        self._issuer = issuer
        self._audience = audience

    def verify(self, token: str) -> dict[str, Any]:
        signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        claims = self._jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=self._audience,
            issuer=self._issuer,
            options={"require": ["exp", "iat", "sub"]},
        )
        return cast(dict[str, Any], claims)


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
        limiter = cast(
            RateLimiter,
            getattr(request.app.state, "rate_limiter", self._limiter),
        )
        try:
            allowed = limiter.allow(f"{client}:{request.url.path}")
        except Exception as exc:
            metrics.increment("rate_limit_backend_failure_total")
            logger.warning(
                "rate_limit.backend_unavailable",
                extra={"path": request.url.path, "error_type": type(exc).__name__},
            )
            return JSONResponse(
                status_code=503,
                content={"detail": "rate limit backend unavailable"},
            )
        if not allowed:
            return JSONResponse(status_code=429, content={"detail": "rate limit exceeded"})
        return await call_next(request)


def _claim_values(claims: dict[str, Any], name: str) -> frozenset[str]:
    value = claims.get(name, [])
    if isinstance(value, str):
        return frozenset(item for item in value.replace(",", " ").split() if item)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return frozenset(value)
    raise HTTPException(status_code=401, detail=f"invalid {name} claim")


def _audit_denial(request: Request, principal: Principal, reason: str) -> None:
    metrics.increment("authorization_denied_total")
    log_event(
        logger,
        logging.WARNING,
        "authorization.denied",
        customer_id="-",
        correlation_id=request.headers.get("traceparent", "-"),
        result="denied",
        duration_ms=0,
        subject=principal.subject,
        reason=reason,
        path=request.url.path,
    )


def require_principal(request: Request) -> Principal:
    settings: Settings = request.app.state.settings
    if settings.auth_mode == "static" and settings.api_token is None:
        raise HTTPException(status_code=503, detail="API token is not configured")
    authorization = request.headers.get("authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not supplied:
        raise HTTPException(status_code=401, detail="invalid bearer token")
    if settings.auth_mode == "oidc":
        verifier = cast(TokenVerifier, request.app.state.token_verifier)
        try:
            claims = verifier.verify(supplied)
            subject = claims.get("sub")
            if not isinstance(subject, str) or not subject:
                raise HTTPException(status_code=401, detail="invalid sub claim")
            customer_ids = _claim_values(claims, settings.oidc_customer_claim)
            raw_roles = _claim_values(claims, settings.oidc_role_claim)
            roles = frozenset(Role(value) for value in raw_roles)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid bearer token") from exc
        return Principal(subject=subject, customer_ids=customer_ids, roles=roles)
    assert settings.api_token is not None  # noqa: S101 - checked before parsing header
    expected = settings.api_token.get_secret_value()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid bearer token")
    return Principal(
        subject="api-token",
        customer_ids=settings.api_token_customer_ids,
        roles=frozenset(Role),
    )


def require_roles(*roles: Role) -> Callable[..., Principal]:
    required = frozenset(roles)

    def dependency(
        request: Request,
        principal: Annotated[Principal, Depends(require_principal)],
    ) -> Principal:
        if not principal.has_any_role(required):
            _audit_denial(request, principal, "role")
            raise HTTPException(status_code=403, detail="role access denied")
        return principal

    return dependency


def authorize_customer(request: Request, principal: Principal, customer_id: str) -> None:
    try:
        principal.require_customer(customer_id)
    except HTTPException:
        _audit_denial(request, principal, "customer")
        raise


# Backward-compatible import for integrations using the original dependency name.
require_api_token = require_principal
