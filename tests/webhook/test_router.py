"""HTTP integration tests for /webhook/wecom — TestClient end-to-end.

We override the DecisionStore dependency so each test gets a fresh `:memory:`
DB, decoupled from any file the app would default to.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models import DecisionOutcome
from src.persistence import DecisionStore
from src.webhook.router import get_decision_store


@pytest.fixture
def store() -> DecisionStore:
    return DecisionStore(":memory:")


@pytest.fixture
def client(store: DecisionStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_decision_store] = lambda: store
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _click_payload(event_key: str) -> dict[str, object]:
    """WeCom click event in its native PascalCase wire shape."""
    return {
        "ToUserName": "ww_corp",
        "FromUserName": "user_zhang",
        "CreateTime": 1717200000,
        "MsgType": "event",
        "Event": "click",
        "EventKey": event_key,
    }


class TestUrlVerification:
    def test_get_echoes_echostr_as_plaintext(self, client: TestClient) -> None:
        resp = client.get("/webhook/wecom", params={"echostr": "hello-from-wecom"})
        assert resp.status_code == 200
        assert resp.text == "hello-from-wecom"

    def test_get_without_echostr_returns_422(self, client: TestClient) -> None:
        resp = client.get("/webhook/wecom")
        assert resp.status_code == 422


class TestClickEvents:
    def test_approve_returns_200_and_writes_decision(
        self, client: TestClient, store: DecisionStore
    ) -> None:
        resp = client.post(
            "/webhook/wecom",
            json=_click_payload("approve:customerA:A-001"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "Recorded" in body["detail"]

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert len(results) == 1
        assert results[0].outcome is DecisionOutcome.APPROVED

    def test_snooze_returns_200(self, client: TestClient, store: DecisionStore) -> None:
        resp = client.post(
            "/webhook/wecom",
            json=_click_payload("snooze:customerA:A-001"),
        )
        assert resp.status_code == 200
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert results[0].outcome is DecisionOutcome.SNOOZED

    def test_revise_returns_200_and_does_not_persist(
        self, client: TestClient, store: DecisionStore
    ) -> None:
        resp = client.post(
            "/webhook/wecom",
            json=_click_payload("revise:customerA:A-001"),
        )
        assert resp.status_code == 200
        assert "改方案" in resp.json()["detail"]

        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert results == []

    def test_unknown_action_returns_400(self, client: TestClient) -> None:
        resp = client.post(
            "/webhook/wecom",
            json=_click_payload("bogus:customerA:A-001"),
        )
        assert resp.status_code == 400
        assert "bogus" in resp.json()["detail"]

    def test_unknown_batch_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/webhook/wecom",
            json=_click_payload("approve:customerA:A-DOES-NOT-EXIST"),
        )
        assert resp.status_code == 404


class TestNonClickMessages:
    """Text / voice / image messages must 200 OK without side effects (v0.1 no-op)."""

    def test_text_message_ignored_with_200(self, client: TestClient, store: DecisionStore) -> None:
        payload = {
            "ToUserName": "ww_corp",
            "FromUserName": "user_zhang",
            "CreateTime": 1717200000,
            "MsgType": "text",
            "Content": "随便发的一句",
        }
        resp = client.post("/webhook/wecom", json=payload)
        assert resp.status_code == 200
        assert resp.json()["detail"].startswith("ignored")
        results = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert results == []

    def test_non_click_event_ignored(self, client: TestClient) -> None:
        """E.g. subscribe / unsubscribe / view events — none mean a decision."""
        payload = {
            "ToUserName": "ww_corp",
            "FromUserName": "user_zhang",
            "CreateTime": 1717200000,
            "MsgType": "event",
            "Event": "subscribe",
        }
        resp = client.post("/webhook/wecom", json=payload)
        assert resp.status_code == 200
        assert "ignored" in resp.json()["detail"]


class TestDefaultStoreFactory:
    """Cover the production fallback when no dependency override is wired."""

    def test_get_decision_store_returns_a_real_store(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The package re-exports `router` (APIRouter instance) under the name
        # `src.webhook.router`, shadowing the module. Use importlib to grab the
        # real module so we can monkeypatch its private symbols.
        import importlib

        router_mod = importlib.import_module("src.webhook.router")

        monkeypatch.setattr(router_mod, "_DEFAULT_DB", tmp_path / "x.db")
        router_mod._default_store.cache_clear()

        store = router_mod.get_decision_store()
        assert isinstance(store, DecisionStore)

        # Second call returns the same singleton (lru_cache contract).
        assert router_mod.get_decision_store() is store

        router_mod._default_store.cache_clear()
