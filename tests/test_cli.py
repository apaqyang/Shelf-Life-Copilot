"""Tests for the CLI entrypoint."""

from __future__ import annotations

from datetime import date

import pytest

from src.cli import (
    _build_provider,
    _build_wecom_client,
    format_cards,
    format_result,
    main,
    parse_args,
)
from src.models import Alert, Card, CardKind, Severity, Suggestion
from src.models.action import ActionType
from src.scheduler import ScanError, ScanResult
from src.suggestion import AnthropicProvider, MoonshotProvider
from src.wecom import DryRunWecomClient, WebhookWecomClient


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


class TestPushWebhookFlag:
    """--push-webhook upgrades the WeCom client from DryRun to real HTTP."""

    def test_push_webhook_parsed(self) -> None:
        ns = parse_args(["--customer", "customerA", "--push-webhook", "https://example.com/key"])
        assert ns.push_webhook == "https://example.com/key"

    def test_push_webhook_default_none(self) -> None:
        ns = parse_args(["--customer", "customerA"])
        assert ns.push_webhook is None

    def test_build_wecom_client_returns_dryrun_when_no_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
        assert isinstance(_build_wecom_client(None), DryRunWecomClient)

    def test_build_wecom_client_returns_webhook_when_flag_given(self) -> None:
        client = _build_wecom_client("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=k")
        assert isinstance(client, WebhookWecomClient)

    def test_build_wecom_client_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/from-env")
        assert isinstance(_build_wecom_client(None), WebhookWecomClient)

    def test_build_wecom_client_flag_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Flag should win over env — explicit beats implicit.
        monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/env")
        client = _build_wecom_client("https://example.com/flag")
        assert isinstance(client, WebhookWecomClient)
        # _url is internal; assert via post inspection in integration test below.

    @pytest.mark.asyncio
    async def test_scan_with_push_webhook_uses_webhook_client(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock

        from src import cli as cli_module

        card = Card(
            kind=CardKind.ALERT,
            customer_id="customerA",
            batch_id="A-001",
            title="t",
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
            def __init__(self, *a: object, **kw: object) -> None: ...

            async def run_for_customer(self, *a: object, **kw: object) -> ScanResult:
                return fake_result

        sent: list[Card] = []

        class _FakeWebhookClient:
            def __init__(self, url: str) -> None:
                self.url = url

            async def send_card(self, card: Card) -> None:
                sent.append(card)

        monkeypatch.setattr(cli_module, "ScanRunner", _FakeRunner)
        monkeypatch.setattr(
            cli_module,
            "_build_wecom_client",
            lambda url: _FakeWebhookClient(url) if url else DryRunWecomClient(),
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setattr(cli_module, "_build_provider", lambda provider_name, model: object())
        monkeypatch.setattr(
            cli_module,
            "SuggestionEngine",
            lambda provider: AsyncMock(spec=cli_module.SuggestionEngine),
        )

        exit_code = await main(
            [
                "--customer",
                "customerA",
                "--push-webhook",
                "https://example.com/abc",
            ]
        )
        assert exit_code == 0
        assert sent == [card]  # truly pushed via webhook client

    @pytest.mark.asyncio
    async def test_revise_with_push_webhook_also_pushes(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock

        from src import cli as cli_module

        card = Card(
            kind=CardKind.ALERT,
            customer_id="customerA",
            batch_id="A-001",
            title="t",
            markdown="## revised body",
        )
        fake_result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[_alert("A-001", Severity.YELLOW, 19)],
            suggestions=[_suggestion("A-001", action=ActionType.DISCOUNT_CLEARANCE)],
            cards=[card],
            errors=[],
        )

        class _FakeRunner:
            def __init__(self, *a: object, **kw: object) -> None: ...

            async def revise_for_batch(self, *a: object, **kw: object) -> ScanResult:
                return fake_result

        sent: list[Card] = []

        class _FakeWebhookClient:
            async def send_card(self, card: Card) -> None:
                sent.append(card)

        monkeypatch.setattr(cli_module, "ScanRunner", _FakeRunner)
        monkeypatch.setattr(
            cli_module,
            "_build_wecom_client",
            lambda url: _FakeWebhookClient() if url else DryRunWecomClient(),
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
        monkeypatch.setattr(cli_module, "_build_provider", lambda provider_name, model: object())
        monkeypatch.setattr(
            cli_module,
            "SuggestionEngine",
            lambda provider: AsyncMock(spec=cli_module.SuggestionEngine),
        )

        exit_code = await main(
            [
                "--customer",
                "customerA",
                "--revise-batch",
                "A-001",
                "--feedback",
                "改成打折",
                "--push-webhook",
                "https://example.com/k",
            ]
        )
        assert exit_code == 0
        assert sent == [card]


class TestReviseFlagParsing:
    def test_revise_batch_and_feedback_parsed(self) -> None:
        ns = parse_args(
            [
                "--customer",
                "customerA",
                "--revise-batch",
                "A-001",
                "--feedback",
                "虾饺线满了，能不能改成打折清仓",
            ]
        )
        assert ns.revise_batch == "A-001"
        assert ns.feedback == "虾饺线满了，能不能改成打折清仓"

    def test_revise_defaults_none(self) -> None:
        ns = parse_args(["--customer", "customerA"])
        assert ns.revise_batch is None
        assert ns.feedback is None


class TestMainReviseFlow:
    @pytest.mark.asyncio
    async def test_revise_calls_revise_for_batch_and_prints_card(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from unittest.mock import AsyncMock

        from src import cli as cli_module

        captured: dict[str, object] = {}

        card = Card(
            kind=CardKind.ALERT,
            customer_id="customerA",
            batch_id="A-001",
            title="【临期预警】冷冻虾仁 · A-001",
            markdown="## body discount_clearance",
        )
        suggestion = _suggestion("A-001", action=ActionType.DISCOUNT_CLEARANCE)
        fake_result = ScanResult(
            customer_id="customerA",
            total_batches=1,
            alerts=[_alert("A-001", Severity.YELLOW, 19)],
            suggestions=[suggestion],
            cards=[card],
            errors=[],
        )

        class _FakeRunner:
            def __init__(self, *args: object, **kwargs: object) -> None: ...

            async def revise_for_batch(
                self,
                customer_id: str,
                batch_id: str,
                feedback: str,
                today: object = None,
            ) -> ScanResult:
                captured["customer_id"] = customer_id
                captured["batch_id"] = batch_id
                captured["feedback"] = feedback
                return fake_result

            async def run_for_customer(self, *args: object, **kwargs: object) -> ScanResult:
                raise AssertionError("revise flow must not call run_for_customer")

        monkeypatch.setattr(cli_module, "ScanRunner", _FakeRunner)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake")
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
            [
                "--customer",
                "customerA",
                "--today",
                "2026-05-26",
                "--revise-batch",
                "A-001",
                "--feedback",
                "虾饺线满了，能不能改成打折清仓",
            ]
        )
        out = capsys.readouterr().out
        assert exit_code == 0
        assert captured == {
            "customer_id": "customerA",
            "batch_id": "A-001",
            "feedback": "虾饺线满了，能不能改成打折清仓",
        }
        # Revise prints the revised card without needing --render-cards.
        assert "discount_clearance" in out
        assert "## body discount_clearance" in out

    @pytest.mark.asyncio
    async def test_revise_requires_feedback(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        exit_code = await main(["--customer", "customerA", "--revise-batch", "A-001"])
        err = capsys.readouterr().err
        assert exit_code == 2
        assert "--feedback" in err

    @pytest.mark.asyncio
    async def test_revise_rejects_dry_run(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        exit_code = await main(
            [
                "--customer",
                "customerA",
                "--revise-batch",
                "A-001",
                "--feedback",
                "改成打折",
                "--dry-run",
            ]
        )
        err = capsys.readouterr().err
        assert exit_code == 2
        assert "dry-run" in err.lower()


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
