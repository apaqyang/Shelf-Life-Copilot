"""Tests for the CLI entrypoint."""

from __future__ import annotations

from datetime import date

import pytest

from src.cli import _build_provider, format_cards, format_result, main, parse_args
from src.models import Alert, Card, CardKind, Severity, Suggestion
from src.models.action import ActionType
from src.scheduler import ScanError, ScanResult
from src.suggestion import AnthropicProvider, MoonshotProvider


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

    def test_render_cards_flag(self) -> None:
        ns = parse_args(["--customer", "customerA", "--dry-run", "--render-cards"])
        assert ns.render_cards is True

    def test_render_cards_defaults_off(self) -> None:
        ns = parse_args(["--customer", "customerA"])
        assert ns.render_cards is False

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


class TestFormatCards:
    def test_empty_cards_returns_hint(self) -> None:
        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[],
            suggestions=[],
            errors=[],
        )
        rendered = format_cards(result)
        assert "no cards" in rendered

    def test_cards_rendered_with_separators_and_kind(self) -> None:
        card = Card(
            kind=CardKind.ALERT,
            customer_id="customerA",
            batch_id="A-001",
            title="【临期预警】冷冻虾仁 · A-001",
            markdown="## body",
        )
        result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[],
            suggestions=[],
            cards=[card],
            errors=[],
        )
        rendered = format_cards(result)
        assert "Card #1" in rendered
        assert "alert" in rendered
        assert "A-001" in rendered
        assert "## body" in rendered


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


class TestMainRenderCards:
    @pytest.mark.asyncio
    async def test_dry_run_with_render_cards_emits_hint(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # dry-run produces no suggestions and therefore no cards — render branch must
        # still execute cleanly and emit the "no cards" hint.
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        exit_code = await main(
            [
                "--customer",
                "customerA",
                "--today",
                "2026-05-26",
                "--dry-run",
                "--render-cards",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "no cards" in captured.out

    @pytest.mark.asyncio
    async def test_cards_are_sent_to_dry_run_client(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock

        from src import cli as cli_module

        card = Card(
            kind=CardKind.ALERT,
            customer_id="customerA",
            batch_id="A-001",
            title="【临期预警】冷冻虾仁 · A-001",
            markdown="## body",
        )
        fake_result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[],
            suggestions=[],
            cards=[card],
            errors=[],
        )

        class _FakeRunner:
            def __init__(self, *args: object, **kwargs: object) -> None: ...

            async def run_for_customer(self, *args: object, **kwargs: object) -> ScanResult:
                return fake_result

        monkeypatch.setattr(cli_module, "ScanRunner", _FakeRunner)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        # Avoid constructing real provider HTTP clients in main().
        monkeypatch.setattr(
            cli_module,
            "_build_provider",
            lambda provider_name, model: object(),
        )
        monkeypatch.setattr(
            cli_module,
            "SuggestionEngine",
            lambda provider: AsyncMock(spec=cli_module.SuggestionEngine),
        )

        exit_code = await main(
            ["--customer", "customerA", "--today", "2026-05-26", "--render-cards"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Card #1" in captured.out
        assert "## body" in captured.out


class TestBuildProvider:
    def test_anthropic_returns_provider_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        provider = _build_provider("anthropic", None)
        assert isinstance(provider, AnthropicProvider)
        assert provider.model_name == "claude-sonnet-4-6"

    def test_anthropic_respects_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        provider = _build_provider("anthropic", "claude-opus-4-7")
        assert isinstance(provider, AnthropicProvider)
        assert provider.model_name == "claude-opus-4-7"

    def test_anthropic_returns_none_without_key(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = _build_provider("anthropic", None)
        assert result is None
        assert "ANTHROPIC_API_KEY" in capsys.readouterr().err

    def test_moonshot_returns_provider_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test")
        provider = _build_provider("moonshot", None)
        assert isinstance(provider, MoonshotProvider)
        assert provider.model_name == "moonshot-v1-32k"

    def test_moonshot_respects_model_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-test")
        provider = _build_provider("moonshot", "kimi-latest")
        assert isinstance(provider, MoonshotProvider)
        assert provider.model_name == "kimi-latest"

    def test_moonshot_returns_none_without_key(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        result = _build_provider("moonshot", None)
        assert result is None
        assert "MOONSHOT_API_KEY" in capsys.readouterr().err


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
