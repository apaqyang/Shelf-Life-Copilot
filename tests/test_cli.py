"""Tests for the CLI entrypoint."""

from __future__ import annotations

from datetime import date

import pytest

from src.cli import format_result, main, parse_args
from src.models import Alert, Severity, Suggestion
from src.models.action import ActionType
from src.scheduler import ScanError, ScanResult


def _alert(batch_id: str, severity: Severity, days_left: int) -> Alert:
    return Alert(
        batch_id=batch_id,
        customer_id="customerA",
        severity=severity,
        days_left=days_left,
    )


def _suggestion(
    batch_id: str,
    *,
    action: ActionType = ActionType.TRANSFORM,
    is_standard: bool = True,
) -> Suggestion:
    return Suggestion(
        batch_id=batch_id,
        customer_id="customerA",
        action=action,
        savings_estimate=8500.0,
        rationale="历史采纳率高",
        confidence=0.85,
        is_standard=is_standard,
        llm_model="claude-sonnet-4-6",
    )


class TestParseArgs:
    def test_minimum_args(self) -> None:
        ns = parse_args(["--customer", "customerA"])
        assert ns.customer == "customerA"
        assert ns.today is None
        assert ns.dry_run is False

    def test_today_parsed_as_date(self) -> None:
        ns = parse_args(["--customer", "customerA", "--today", "2026-05-26"])
        assert ns.today == date(2026, 5, 26)

    def test_dry_run_flag(self) -> None:
        ns = parse_args(["--customer", "customerA", "--dry-run"])
        assert ns.dry_run is True

    def test_missing_customer_exits(self) -> None:
        with pytest.raises(SystemExit):
            parse_args([])


class TestFormatResult:
    def test_no_alerts_message(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=2,
            alerts=[],
            suggestions=[],
            errors=[],
        )
        rendered = format_result(result)
        assert "customerA" in rendered
        assert "no alerts" in rendered

    def test_alerts_block_rendered(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=2,
            alerts=[_alert("A-001", Severity.YELLOW, 19)],
            suggestions=[],
            errors=[],
        )
        rendered = format_result(result)
        assert "A-001" in rendered
        assert "yellow" in rendered
        assert "剩余 19 天" in rendered

    def test_standard_suggestion_no_tag(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[_alert("A-001", Severity.YELLOW, 19)],
            suggestions=[_suggestion("A-001")],
            errors=[],
        )
        rendered = format_result(result)
        assert "transform" in rendered
        assert "8,500" in rendered
        assert "非标准" not in rendered

    def test_nonstandard_suggestion_carries_tag(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[_alert("A-001", Severity.YELLOW, 19)],
            suggestions=[_suggestion("A-001", is_standard=False)],
            errors=[],
        )
        rendered = format_result(result)
        assert "非标准动作" in rendered

    def test_errors_block_rendered(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[_alert("A-001", Severity.YELLOW, 19)],
            suggestions=[],
            errors=[ScanError(batch_id="A-001", message="rate limit")],
        )
        rendered = format_result(result)
        assert "A-001" in rendered
        assert "rate limit" in rendered


class TestMainDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_succeeds_without_api_key(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        exit_code = await main(["--customer", "customerA", "--today", "2026-05-26", "--dry-run"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "customerA" in captured.out
        assert "Alerts:" in captured.out


class TestMainMissingApiKey:
    @pytest.mark.asyncio
    async def test_returns_2_when_api_key_missing(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        exit_code = await main(["--customer", "customerA", "--today", "2026-05-26"])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "ANTHROPIC_API_KEY" in captured.err
