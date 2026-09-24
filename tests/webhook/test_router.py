"""HTTP integration tests for /webhook/wecom — TestClient end-to-end.

We override the DecisionStore dependency so each test gets a fresh `:memory:`
DB, decoupled from any file the app would default to.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models import DecisionOutcome
from src.persistence import DecisionStore, IdempotencyStore, SuggestionStore
from src.runtime.config import Settings
from src.webhook.router import (
    _validate_event_timestamp,
    get_decision_store,
    get_idempotency_store,
    get_runtime_settings,
    get_suggestion_store,
)


@pytest.fixture
def store() -> DecisionStore:
    return DecisionStore(":memory:")


@pytest.fixture
def suggestion_store() -> SuggestionStore:
    return SuggestionStore(":memory:")


@pytest.fixture
def idempotency_store() -> IdempotencyStore:
    return IdempotencyStore(":memory:")


@pytest.fixture
def client(
    store: DecisionStore,
    suggestion_store: SuggestionStore,
    idempotency_store: IdempotencyStore,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_decision_store] = lambda: store
    app.dependency_overrides[get_suggestion_store] = lambda: suggestion_store
    app.dependency_overrides[get_idempotency_store] = lambda: idempotency_store
    app.dependency_overrides[get_runtime_settings] = lambda: Settings(_env_file=None)  # type: ignore[call-arg]
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _click_payload(event_key: str) -> dict[str, object]:
    """WeCom click event in its native PascalCase wire shape."""
    return {
        "ToUserName": "ww_corp",
        "FromUserName": "user_zhang",
        "CreateTime": int(datetime.now(UTC).timestamp()),
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

    def test_duplicate_callback_replays_response_without_duplicate_decision(
        self, client: TestClient, store: DecisionStore
    ) -> None:
        payload = _click_payload("snooze:customerA:A-001")
        first = client.post("/webhook/wecom", json=payload)
        second = client.post("/webhook/wecom", json=payload)
        assert second.json() == first.json()
        rows = store.list_for_period(
            "customerA",
            start=datetime(2026, 1, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert len(rows) == 1

    def test_stale_callback_is_rejected(self, client: TestClient) -> None:
        payload = _click_payload("approve:customerA:A-001")
        payload["CreateTime"] = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        response = client.post("/webhook/wecom", json=payload)
        assert response.status_code == 400
        assert "replay window" in response.json()["detail"]

    def test_callback_already_processing_returns_conflict(
        self, client: TestClient, idempotency_store: IdempotencyStore
    ) -> None:
        payload = _click_payload("approve:customerA:A-001")
        from src.webhook.schemas import WecomEvent

        event = WecomEvent.model_validate(payload)
        idempotency_store.claim(event.stable_event_id, "wecom_callback")
        response = client.post("/webhook/wecom", json=payload)
        assert response.status_code == 409

    def test_unexpected_handler_failure_releases_claim(
        self,
        client: TestClient,
        idempotency_store: IdempotencyStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        payload = _click_payload("approve:customerA:A-001")
        from src.webhook.schemas import WecomEvent

        event = WecomEvent.model_validate(payload)

        def fail(*_args: object, **_kwargs: object) -> str:
            raise RuntimeError("boom")

        import importlib

        router_module = importlib.import_module("src.webhook.router")
        monkeypatch.setattr(router_module, "handle_click", fail)
        with pytest.raises(RuntimeError, match="boom"):
            client.post("/webhook/wecom", json=payload)
        assert idempotency_store.claim(event.stable_event_id, "wecom_callback") is None


class TestNonClickMessages:
    """Text / voice / image messages must 200 OK without side effects (v0.1 no-op)."""

    def test_text_message_ignored_with_200(self, client: TestClient, store: DecisionStore) -> None:
        payload = {
            "ToUserName": "ww_corp",
            "FromUserName": "user_zhang",
            "CreateTime": int(datetime.now(UTC).timestamp()),
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
            "CreateTime": int(datetime.now(UTC).timestamp()),
            "MsgType": "event",
            "Event": "subscribe",
        }
        resp = client.post("/webhook/wecom", json=payload)
        assert resp.status_code == 200
        assert "ignored" in resp.json()["detail"]


class TestLifespanStoreDependencies:
    """Production dependencies resolve stores owned by the FastAPI lifespan."""

    def test_dependencies_return_app_state_stores(
        self, store: DecisionStore, suggestion_store: SuggestionStore
    ) -> None:
        from fastapi import FastAPI, Request

        test_app = FastAPI()
        test_app.state.decision_store = store
        test_app.state.suggestion_store = suggestion_store
        test_app.state.idempotency_store = IdempotencyStore(":memory:")
        test_app.state.settings = Settings(_env_file=None)  # type: ignore[call-arg]
        request = Request({"type": "http", "app": test_app})

        assert get_decision_store(request) is store
        assert get_suggestion_store(request) is suggestion_store
        assert isinstance(get_idempotency_store(request), IdempotencyStore)
        assert isinstance(get_runtime_settings(request), Settings)


def test_validate_event_timestamp_rejects_naive_now() -> None:
    from src.webhook.schemas import WecomEvent

    event = WecomEvent(
        ToUserName="corp",
        FromUserName="user",
        CreateTime=1,
        MsgType="event",
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        _validate_event_timestamp(event, 300, now=datetime(2026, 1, 1))


def test_message_id_is_preferred_as_stable_event_id() -> None:
    from src.webhook.schemas import WecomEvent

    event = WecomEvent(
        ToUserName="corp",
        FromUserName="user",
        CreateTime=1,
        MsgType="event",
        MsgId="message-1",
    )
    assert event.stable_event_id == "wecom:message-1"


class TestSuggestionStoreIntegration:
    """End-to-end: a persisted Suggestion's action / savings_estimate flows
    through the webhook click into the Decision row."""

    def test_approve_uses_persisted_suggestion(
        self,
        client: TestClient,
        store: DecisionStore,
        suggestion_store: SuggestionStore,
    ) -> None:
        from datetime import UTC, datetime

        from src.models import ActionType, Suggestion

        suggestion_store.save(
            Suggestion(
                batch_id="A-001",
                customer_id="customerA",
                action=ActionType.DISCOUNT_CLEARANCE,
                savings_estimate=6200.0,
                rationale="清仓渠道吸收率 75%",
                confidence=0.78,
                is_standard=True,
                generated_at=datetime(2026, 5, 26, 7, 5, tzinfo=UTC),
                llm_model="claude-sonnet-4-6",
            )
        )

        resp = client.post(
            "/webhook/wecom",
            json=_click_payload("approve:customerA:A-001"),
        )
        assert resp.status_code == 200

        rows = store.list_for_period(
            "customerA",
            start=datetime(2026, 5, 1, tzinfo=UTC),
            end=datetime(2027, 1, 1, tzinfo=UTC),
        )
        assert len(rows) == 1
        assert rows[0].action is ActionType.DISCOUNT_CLEARANCE
        assert rows[0].savings_estimate == 6200.0
