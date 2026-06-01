"""Tests for Settings — env / .env loading + sensible v0.1 defaults."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime.config import Settings, get_settings


class TestDefaults:
    def test_defaults_when_no_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Clear every var we read so we see pure defaults.
        for k in (
            "APP_ENV",
            "LOG_LEVEL",
            "DECISIONS_DB_PATH",
            "REPORTS_OUTPUT_DIR",
            "SCAN_CUSTOMERS",
            "SCAN_HOUR",
            "SCAN_MINUTE",
            "MONTHLY_DAY",
            "MONTHLY_HOUR",
            "MONTHLY_MINUTE",
            "WECOM_WEBHOOK_URL",
            "ANTHROPIC_API_KEY",
            "MOONSHOT_API_KEY",
            "LLM_PROVIDER",
        ):
            monkeypatch.delenv(k, raising=False)

        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.app_env == "development"
        assert s.decisions_db_path == Path("data/decisions.db")
        assert s.reports_output_dir == Path("docs/demo_samples")
        assert s.scan_customers_list == ["customerA", "customerB"]
        assert s.scan_hour == 7
        assert s.scan_minute == 0
        assert s.monthly_day == 1
        assert s.monthly_hour == 8
        assert s.monthly_minute == 0
        assert s.wecom_webhook_url is None
        assert s.anthropic_api_key is None
        assert s.moonshot_api_key is None
        assert s.llm_provider == "anthropic"
        assert s.customer_baselines == {
            "customerA": 1_500_000.0,
            "customerB": 860_000.0,
        }


class TestEnvOverrides:
    def test_scan_customers_comma_separated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCAN_CUSTOMERS", "customerA, customerC ,customerD")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.scan_customers_list == ["customerA", "customerC", "customerD"]

    def test_scan_customers_strips_empty_entries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCAN_CUSTOMERS", "customerA,,customerB,")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.scan_customers_list == ["customerA", "customerB"]

    def test_paths_resolved_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DECISIONS_DB_PATH", "/tmp/test.db")
        monkeypatch.setenv("REPORTS_OUTPUT_DIR", "/tmp/reports")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.decisions_db_path == Path("/tmp/test.db")
        assert s.reports_output_dir == Path("/tmp/reports")

    def test_cron_hours_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCAN_HOUR", "9")
        monkeypatch.setenv("MONTHLY_DAY", "5")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.scan_hour == 9
        assert s.monthly_day == 5

    def test_webhook_and_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/k")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.wecom_webhook_url == "https://example.com/k"
        assert s.anthropic_api_key == "sk-test"

    def test_llm_provider_choices(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "moonshot")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.llm_provider == "moonshot"


class TestActiveLLMKey:
    """`active_llm_key` returns the key for the *currently selected* provider."""

    def test_returns_anthropic_key_when_provider_is_anthropic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-moonshot")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.active_llm_key == "sk-anthropic"

    def test_returns_moonshot_key_when_provider_is_moonshot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "moonshot")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anthropic")
        monkeypatch.setenv("MOONSHOT_API_KEY", "sk-moonshot")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.active_llm_key == "sk-moonshot"

    def test_returns_none_when_key_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.active_llm_key is None


class TestValidation:
    def test_invalid_hour_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SCAN_HOUR", "24")
        with pytest.raises(ValueError, match="hour"):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_invalid_minute_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONTHLY_MINUTE", "60")
        with pytest.raises(ValueError, match="minute"):
            Settings(_env_file=None)  # type: ignore[call-arg]

    def test_invalid_day_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MONTHLY_DAY", "29")
        with pytest.raises(ValueError, match="monthly_day"):
            Settings(_env_file=None)  # type: ignore[call-arg]


class TestGetSettings:
    def test_lru_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Repeated calls return the same instance (cached)."""
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()
