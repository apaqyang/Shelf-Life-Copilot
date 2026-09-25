"""Authenticated and idempotent manual scan and work-order APIs."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import router
from src.models import (
    ActionType,
    Alert,
    Decision,
    DecisionOutcome,
    Severity,
    WorkOrder,
    WorkOrderStatus,
)
from src.runtime.config import Settings
from src.runtime.lifespan import build_lifespan
from src.runtime.security import RequestGuardMiddleware
from src.scheduler import ScanError, ScanResult


def _app(settings: Settings) -> FastAPI:
    app = FastAPI(lifespan=build_lifespan(settings))
    app.add_middleware(
        RequestGuardMiddleware,
        max_body_bytes=settings.max_request_body_bytes,
        rate_limit_requests=settings.rate_limit_requests,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
    )
    app.include_router(router)
    return app


@pytest.fixture(autouse=True)
def _empty_plugins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "plugins"
    root.mkdir()
    monkeypatch.setattr("src.plugins.loader.DEFAULT_PLUGINS_ROOT", root)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        api_token="secret",
        llm_provider="offline",
        decisions_db_path=tmp_path / "api.db",
        reports_output_dir=tmp_path / "reports",
        scan_customers="customerA",
    )


def _headers(key: str = "request-1") -> dict[str, str]:
    return {"Authorization": "Bearer secret", "Idempotency-Key": key}


def test_manual_scan_requires_auth_and_idempotency_key(settings: Settings) -> None:
    with TestClient(_app(settings)) as client:
        assert client.post("/api/scans", json={"customer_id": "customerA"}).status_code == 401
        assert (
            client.post(
                "/api/scans",
                json={"customer_id": "customerA"},
                headers={"Authorization": "Bearer secret"},
            ).status_code
            == 422
        )


def test_tenant_query_api_lists_only_authorized_data(settings: Settings) -> None:
    with TestClient(_app(settings)) as client:
        customers = client.get("/api/customers", headers={"Authorization": "Bearer secret"})
        batches = client.get(
            "/api/customers/customerA/batches?limit=2",
            headers={"Authorization": "Bearer secret"},
        )
        denied = client.get(
            "/api/customers/customerB/batches",
            headers={"Authorization": "Bearer secret"},
        )
        orders = client.get(
            "/api/customers/customerA/work-orders",
            headers={"Authorization": "Bearer secret"},
        )
    assert customers.json()["items"] == [{"customer_id": "customerA", "industry": "frozen_seafood"}]
    assert len(batches.json()["items"]) == 2
    assert batches.json()["page"] == {"next_cursor": 2}
    assert denied.status_code == 403
    assert orders.json() == {"items": [], "page": {"next_cursor": None}}


def test_quality_outcome_api_uses_verified_persistence_data(settings: Settings) -> None:
    with TestClient(_app(settings)) as client:
        response = client.get(
            "/api/quality/outcomes",
            params={
                "customer_id": "customerA",
                "start": "2026-01-01T00:00:00Z",
                "end": "2027-01-01T00:00:00Z",
            },
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 200
    assert response.json()["customer_id"] == "customerA"
    assert response.json()["verified_count"] == 0
    assert response.json()["gate_passed"] is False

    with TestClient(_app(settings)) as client:
        invalid = client.get(
            "/api/quality/outcomes",
            params={
                "customer_id": "customerA",
                "start": "2027-01-01T00:00:00",
                "end": "2026-01-01T00:00:00",
            },
            headers={"Authorization": "Bearer secret"},
        )
    assert invalid.status_code == 422


def test_query_api_auth_validation_and_missing_source(settings: Settings) -> None:
    expanded = settings.model_copy(update={"api_token_customers": "customerA,missing"})
    with TestClient(_app(expanded)) as client:
        assert client.get("/api/customers").status_code == 401
        customers = client.get("/api/customers", headers={"Authorization": "Bearer secret"})
        missing = client.get(
            "/api/customers/missing/batches", headers={"Authorization": "Bearer secret"}
        )
    assert len(customers.json()["items"]) == 1
    assert missing.status_code == 404


def test_optimization_plan_requires_gate_and_human_approval(settings: Settings) -> None:
    app = _app(settings)
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        created = client.post(
            "/api/optimization-plans",
            json={
                "customer_id": "customerA",
                "today": "2026-05-26",
                "capacity_by_action": {"transform": 1000},
            },
            headers=headers,
        )
        assert created.status_code == 200
        plan = created.json()["plan"]
        assert created.json()["gate"]["passed"] is True
        assert plan["status"] == "pending_approval"
        fetched = client.get(f"/api/optimization-plans/{plan['plan_id']}", headers=headers)
        missing_operator = client.post(
            f"/api/optimization-plans/{plan['plan_id']}/execute", headers=headers
        )
        executed = client.post(
            f"/api/optimization-plans/{plan['plan_id']}/execute",
            headers={**headers, "X-Operator-ID": "director-1"},
        )
        duplicate = client.post(
            f"/api/optimization-plans/{plan['plan_id']}/execute",
            headers={**headers, "X-Operator-ID": "director-1"},
        )
        orders = client.get("/api/customers/customerA/work-orders", headers=headers).json()["items"]
    assert fetched.json()["status"] == "pending_approval"
    assert missing_operator.status_code == 422
    assert executed.json()["status"] == "executed"
    assert executed.json()["approved_by"] == "director-1"
    assert duplicate.status_code == 409
    assert orders


def test_optimization_api_errors_are_tenant_safe(settings: Settings) -> None:
    app = _app(settings)
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        missing = client.get("/api/optimization-plans/nope", headers=headers)
        execute_missing = client.post(
            "/api/optimization-plans/nope/execute",
            headers={**headers, "X-Operator-ID": "director"},
        )
        app.state.optimization_gate = app.state.optimization_gate.model_copy(
            update={"passed": False}
        )
        gated = client.post(
            "/api/optimization-plans",
            json={"customer_id": "customerA", "capacity_by_action": {}},
            headers=headers,
        )
    assert missing.status_code == 404
    assert execute_missing.status_code == 404
    assert gated.status_code == 503


def test_optimization_api_maps_repository_and_small_inventory_errors(
    settings: Settings,
) -> None:
    app = _app(settings)
    headers = {"Authorization": "Bearer secret"}
    with TestClient(app) as client:
        repository = MagicMock()
        repository.load_batches.side_effect = FileNotFoundError("gone")
        app.state.batch_repository = repository
        missing = client.post(
            "/api/optimization-plans",
            json={"customer_id": "customerA", "capacity_by_action": {}},
            headers=headers,
        )
        repository.load_batches.side_effect = None
        repository.load_batches.return_value = [
            MagicMock(
                batch_id="one",
                material_name="one",
                expiry_date=datetime(2026, 1, 2, tzinfo=UTC).date(),
                stock_qty=1,
            )
        ]
        repository.load_customer_config.return_value = MagicMock(
            enabled_actions=[ActionType.REPORT_LOSS]
        )
        too_small = client.post(
            "/api/optimization-plans",
            json={
                "customer_id": "customerA",
                "today": "2026-01-01",
                "capacity_by_action": {},
            },
            headers=headers,
        )
    assert missing.status_code == 404
    assert too_small.status_code == 409


def test_optimization_api_rejects_a_zero_allocation_plan(settings: Settings) -> None:
    with TestClient(_app(settings)) as client:
        response = client.post(
            "/api/optimization-plans",
            json={
                "customer_id": "customerA",
                "today": "2026-05-26",
                "capacity_by_action": {},
            },
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "plan allocates no inventory"


def test_manual_scan_returns_batch_summary_and_replays_result(settings: Settings) -> None:
    with TestClient(_app(settings)) as client:
        payload = {"customer_id": "customerA", "today": "2026-05-26", "skip_llm": True}
        first = client.post("/api/scans", json=payload, headers=_headers())
        second = client.post("/api/scans", json=payload, headers=_headers())
    assert first.status_code == 200
    assert second.json() == first.json()
    assert first.json()["total_batches"] == 7
    assert len(first.json()["batch_results"]) == 7
    assert {item["status"] for item in first.json()["batch_results"]} == {"succeeded"}


def test_manual_scan_reports_per_batch_failure_and_processing_conflict(
    settings: Settings,
) -> None:
    app = _app(settings)
    with TestClient(app) as client:
        alert = Alert(
            batch_id="A-001",
            customer_id="customerA",
            severity=Severity.RED,
            days_left=1,
        )
        app.state.scan_runner.run_for_customer = AsyncMock(
            return_value=ScanResult(
                customer_id="customerA",
                total_batches=1,
                alerts=[alert],
                suggestions=[],
                cards=[],
                errors=[ScanError(batch_id="A-001", message="provider failed")],
            )
        )
        response = client.post(
            "/api/scans",
            json={"customer_id": "customerA"},
            headers=_headers("failed-batch"),
        )
        app.state.idempotency_store.claim("manual_scan:processing", "manual_scan")
        conflict = client.post(
            "/api/scans",
            json={"customer_id": "customerA"},
            headers=_headers("processing"),
        )
    assert response.json()["batch_results"] == [
        {"batch_id": "A-001", "status": "failed", "detail": "provider failed"}
    ]
    assert conflict.status_code == 409


def test_manual_scan_reports_unknown_customer_and_missing_provider(
    settings: Settings,
) -> None:
    with TestClient(_app(settings)) as client:
        missing = client.post(
            "/api/scans",
            json={"customer_id": "missing", "skip_llm": True},
            headers=_headers("missing"),
        )
    assert missing.status_code == 403

    unavailable = settings.model_copy(update={"llm_provider": "anthropic"})
    with TestClient(_app(unavailable)) as client:
        response = client.post(
            "/api/scans",
            json={"customer_id": "customerA"},
            headers=_headers("unavailable"),
        )
    assert response.status_code == 503


def test_work_order_completion_updates_receipt_and_decision(settings: Settings) -> None:
    app = _app(settings)
    timestamp = datetime(2026, 9, 24, tzinfo=UTC)
    with TestClient(app) as client:
        decision = Decision(
            batch_id="A-001",
            customer_id="customerA",
            material_name="冷冻虾仁",
            decided_at=timestamp,
            action=ActionType.TRANSFORM,
            outcome=DecisionOutcome.APPROVED,
            savings_estimate=100,
        )
        order = WorkOrder(
            work_order_id="WO-API",
            batch_id=decision.batch_id,
            customer_id=decision.customer_id,
            material_name=decision.material_name,
            action=decision.action,
            created_at=timestamp,
            updated_at=timestamp,
        )
        app.state.decision_store.record_approval(decision, order, idempotency_key="approval")
        app.state.work_order_store.transition("WO-API", WorkOrderStatus.IN_PROGRESS, at=timestamp)
        headers = {**_headers("complete-1"), "X-Operator-ID": "worker-7"}
        payload = {"actual_qty": 88, "actual_savings": 95, "source": "wecom_form"}
        first = client.post("/api/work-orders/WO-API/complete", json=payload, headers=headers)
        second = client.post("/api/work-orders/WO-API/complete", json=payload, headers=headers)
        decisions = app.state.decision_store.list_for_period(
            "customerA",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2027, 1, 1, tzinfo=UTC),
        )
    assert first.status_code == 200
    assert second.json() == first.json()
    receipt = first.json()["work_order"]
    assert receipt["status"] == "completed"
    assert receipt["completed_by"] == "worker-7"
    assert receipt["completion_source"] == "wecom_form"
    assert decisions[0].savings_estimate == 100
    assert decisions[0].actual_savings == 95


def test_work_order_completion_handles_missing_and_invalid_state(settings: Settings) -> None:
    app = _app(settings)
    with TestClient(app) as client:
        headers = {**_headers(), "X-Operator-ID": "worker"}
        response = client.post(
            "/api/work-orders/missing/complete",
            json={"actual_qty": 1, "actual_savings": 1, "source": "api"},
            headers=headers,
        )
        timestamp = datetime(2026, 9, 24, tzinfo=UTC)
        decision = Decision(
            batch_id="A-002",
            customer_id="customerA",
            material_name="pending",
            decided_at=timestamp,
            action=ActionType.TRANSFORM,
            outcome=DecisionOutcome.APPROVED,
            savings_estimate=10,
        )
        order = WorkOrder(
            work_order_id="WO-PENDING",
            batch_id=decision.batch_id,
            customer_id=decision.customer_id,
            material_name=decision.material_name,
            action=decision.action,
            created_at=timestamp,
            updated_at=timestamp,
        )
        app.state.decision_store.record_approval(decision, order, idempotency_key="approval-2")
        invalid = client.post(
            "/api/work-orders/WO-PENDING/complete",
            json={"actual_qty": 1, "actual_savings": 1, "source": "api"},
            headers={**_headers("invalid-state"), "X-Operator-ID": "worker"},
        )
    assert response.status_code == 404
    assert invalid.status_code == 409


@pytest.mark.parametrize("error", [ValueError("bad input"), RuntimeError("boom")])
def test_manual_scan_unexpected_failures_release_idempotency_claim(
    settings: Settings, error: Exception
) -> None:
    app = _app(settings)
    with TestClient(app) as client:
        app.state.scan_runner.run_for_customer = AsyncMock(side_effect=error)
        with pytest.raises(type(error), match=str(error)):
            client.post(
                "/api/scans",
                json={"customer_id": "customerA"},
                headers=_headers("retryable"),
            )
        assert app.state.idempotency_store.claim("manual_scan:retryable", "manual_scan") is None


def test_work_order_unexpected_failure_releases_claim(settings: Settings) -> None:
    app = _app(settings)
    with TestClient(app) as client:
        app.state.work_order_store.get = MagicMock(
            return_value=WorkOrder(
                work_order_id="WO",
                batch_id="A-001",
                customer_id="customerA",
                material_name="test",
                action=ActionType.TRANSFORM,
            )
        )
        app.state.work_order_store.complete = MagicMock(side_effect=RuntimeError("boom"))
        with pytest.raises(RuntimeError, match="boom"):
            client.post(
                "/api/work-orders/WO/complete",
                json={"actual_qty": 1, "actual_savings": 1, "source": "api"},
                headers={**_headers("retry-complete"), "X-Operator-ID": "worker"},
            )
        assert (
            app.state.idempotency_store.claim(
                "work_order_completion:retry-complete", "work_order_completion"
            )
            is None
        )


def test_command_store_lookup_failures_release_claim(settings: Settings) -> None:
    app = _app(settings)
    with TestClient(app) as client:
        app.state.scan_runner.run_for_customer = AsyncMock(side_effect=FileNotFoundError("gone"))
        scan = client.post(
            "/api/scans",
            json={"customer_id": "customerA", "skip_llm": True},
            headers=_headers("gone"),
        )
        order = WorkOrder(
            work_order_id="WO-KEY",
            batch_id="A-001",
            customer_id="customerA",
            material_name="test",
            action=ActionType.TRANSFORM,
        )
        app.state.work_order_store.get = MagicMock(return_value=order)
        app.state.work_order_store.complete = MagicMock(side_effect=KeyError("gone"))
        completion = client.post(
            "/api/work-orders/WO-KEY/complete",
            json={"actual_qty": 1, "actual_savings": 1, "source": "api"},
            headers={**_headers("key-error"), "X-Operator-ID": "worker"},
        )
    assert scan.status_code == 404
    assert completion.status_code == 404


def test_cross_tenant_work_order_access_is_denied(settings: Settings) -> None:
    restricted = settings.model_copy(update={"api_token_customers": "customerA"})
    app = _app(restricted)
    with TestClient(app) as client:
        app.state.work_order_store.get = MagicMock(
            return_value=WorkOrder(
                work_order_id="WO-B",
                batch_id="B-001",
                customer_id="customerB",
                material_name="other tenant",
                action=ActionType.REPORT_LOSS,
            )
        )
        response = client.post(
            "/api/work-orders/WO-B/complete",
            json={"actual_qty": 1, "actual_savings": 1, "source": "api"},
            headers={**_headers("cross-tenant"), "X-Operator-ID": "worker"},
        )
    assert response.status_code == 403
