"""Authentication, request-size, and rate-limit controls."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Annotated, Any, Protocol

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from src.runtime.config import Settings
from src.runtime.security import (
    OIDCJWTVerifier,
    RequestGuardMiddleware,
    SlidingWindowRateLimiter,
    authorize_customer,
    require_api_token,
    require_roles,
)
from src.runtime.tenant import Principal, Role

ViewerDependency = Annotated[Principal, Depends(require_roles(Role.VIEWER, Role.ADMIN))]
AdminDependency = Annotated[Principal, Depends(require_roles(Role.ADMIN))]


def test_sliding_window_expires_old_requests() -> None:
    limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)
    assert limiter.allow("client", now=1)
    assert limiter.allow("client", now=2)
    assert not limiter.allow("client", now=3)
    assert limiter.allow("client", now=12)
    assert limiter.allow("other-client")


class _Limiter(Protocol):
    def allow(self, key: str, *, now: float | None = None) -> bool: ...


def _guarded_app(*, token: str | None = "secret", limiter: _Limiter | None = None) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(_env_file=None, api_token=token)  # type: ignore[call-arg]
    if limiter is not None:
        app.state.rate_limiter = limiter
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


def test_two_app_instances_use_one_shared_rate_limit_quota() -> None:
    shared = SlidingWindowRateLimiter(limit=2, window_seconds=60)
    first = _guarded_app(limiter=shared)
    second = _guarded_app(limiter=shared)
    headers = {"Authorization": "Bearer secret"}
    with TestClient(first) as first_client, TestClient(second) as second_client:
        assert first_client.post("/api/test", headers=headers).status_code == 200
        assert second_client.post("/api/test", headers=headers).status_code == 200
        assert first_client.post("/api/test", headers=headers).status_code == 429


def test_shared_rate_limit_backend_failure_is_fail_closed() -> None:
    class BrokenLimiter:
        def allow(self, key: str, *, now: float | None = None) -> bool:
            raise RuntimeError("database unavailable")

    with TestClient(_guarded_app(limiter=BrokenLimiter())) as client:
        response = client.post(
            "/api/test",
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 503
    assert response.json() == {"detail": "rate limit backend unavailable"}


def _oidc_app(claims: dict[str, Any] | Exception) -> FastAPI:
    app = FastAPI()
    app.state.settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        auth_mode="oidc",
        oidc_issuer="https://issuer.example",
        oidc_audience="shelf-life",
        oidc_jwks_url="https://issuer.example/jwks",
    )

    class Verifier:
        def verify(self, token: str) -> dict[str, Any]:
            if isinstance(claims, Exception):
                raise claims
            return claims

    app.state.token_verifier = Verifier()

    @app.get("/viewer")
    async def viewer(principal: ViewerDependency) -> dict[str, str]:
        return {"subject": principal.subject}

    @app.get("/admin")
    async def admin(
        request: Request,
        principal: AdminDependency,
    ) -> dict[str, str]:
        authorize_customer(request, principal, "tenant-b")
        return {"subject": principal.subject}

    return app


def test_oidc_claims_drive_identity_roles_and_tenant_audit() -> None:
    app = _oidc_app({"sub": "user-1", "customer_ids": "tenant-a,tenant-b", "roles": ["viewer"]})
    with TestClient(app) as client:
        accepted = client.get("/viewer", headers={"Authorization": "Bearer signed"})
        role_denied = client.get("/admin", headers={"Authorization": "Bearer signed"})
    assert accepted.json() == {"subject": "user-1"}
    assert role_denied.status_code == 403

    tenant_app = _oidc_app({"sub": "admin", "customer_ids": ["tenant-a"], "roles": "admin"})
    with TestClient(tenant_app) as client:
        tenant_denied = client.get("/admin", headers={"Authorization": "Bearer signed"})
    assert tenant_denied.status_code == 403


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "", "customer_ids": ["tenant"], "roles": ["viewer"]},
        {"sub": "user", "customer_ids": 42, "roles": ["viewer"]},
        {"sub": "user", "customer_ids": ["tenant"], "roles": ["unknown"]},
        RuntimeError("invalid signature"),
    ],
)
def test_oidc_invalid_tokens_and_claims_are_rejected(claims: dict[str, Any] | Exception) -> None:
    with TestClient(_oidc_app(claims)) as client:
        response = client.get("/viewer", headers={"Authorization": "Bearer signed"})
        missing = client.get("/viewer")
    assert response.status_code == 401
    assert missing.status_code == 401


def test_oidc_jwks_verifier_uses_restricted_algorithms(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}

    class JWKClient:
        def __init__(self, url: str, *, cache_keys: bool) -> None:
            calls["client"] = (url, cache_keys)

        def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
            calls["token"] = token
            return SimpleNamespace(key="public-key")

    def decode(token: str, key: str, **kwargs: Any) -> dict[str, Any]:
        calls["decode"] = (token, key, kwargs)
        return {"sub": "user"}

    monkeypatch.setattr(
        "src.runtime.security.import_module",
        lambda _name: SimpleNamespace(PyJWKClient=JWKClient, decode=decode),
    )
    verifier = OIDCJWTVerifier(
        jwks_url="https://issuer.example/jwks",
        issuer="https://issuer.example",
        audience="shelf-life",
    )
    assert verifier.verify("signed") == {"sub": "user"}
    assert calls["client"] == ("https://issuer.example/jwks", True)
    assert calls["decode"][2]["algorithms"] == ["RS256", "ES256"]
