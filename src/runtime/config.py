"""Runtime Settings — pydantic-settings reads `.env` + environment.

Single source of truth for the long-running uvicorn process. CLI tools and
short-lived scripts still take their own args; this exists so a deployed
service has one well-typed config object, not scattered `os.environ.get`s.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven runtime config."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── infra ─────────────────────────────────────────────────────────────
    app_env: str = "development"
    log_level: str = "INFO"

    # ── persistence / output ──────────────────────────────────────────────
    decisions_db_path: Path = Path("data/decisions.db")
    reports_output_dir: Path = Path("docs/demo_samples")

    # ── daily scan cron ───────────────────────────────────────────────────
    # Comma-separated for friendliness; consumed via `scan_customers_list`.
    scan_customers: str = "customerA,customerB"
    scan_hour: int = 7
    scan_minute: int = 0

    # ── monthly report cron ───────────────────────────────────────────────
    monthly_day: int = 1
    monthly_hour: int = 8
    monthly_minute: int = 0

    # ── WeCom push ────────────────────────────────────────────────────────
    wecom_webhook_url: str | None = None

    # ── LLM provider ──────────────────────────────────────────────────────
    # `offline` is the zero-config demo provider (no API key). Real deployments
    # set ANTHROPIC_API_KEY / MOONSHOT_API_KEY and flip llm_provider accordingly.
    llm_provider: Literal["anthropic", "moonshot", "offline"] = "anthropic"
    anthropic_api_key: str | None = None
    moonshot_api_key: str | None = None

    # ── per-customer baselines (v0.1 hard-coded; v1.0 reads JSON file) ───
    customer_baselines: dict[str, float] = {
        "customerA": 1_500_000.0,
        "customerB": 860_000.0,
    }

    @field_validator("scan_hour", "monthly_hour")
    @classmethod
    def _validate_hour(cls, v: int) -> int:
        if not 0 <= v <= 23:
            raise ValueError(f"hour must be 0..23, got {v}")
        return v

    @field_validator("scan_minute", "monthly_minute")
    @classmethod
    def _validate_minute(cls, v: int) -> int:
        if not 0 <= v <= 59:
            raise ValueError(f"minute must be 0..59, got {v}")
        return v

    @field_validator("monthly_day")
    @classmethod
    def _validate_day(cls, v: int) -> int:
        if not 1 <= v <= 28:
            raise ValueError(f"monthly_day must be 1..28, got {v}")
        return v

    @property
    def scan_customers_list(self) -> list[str]:
        """Comma-separated SCAN_CUSTOMERS → list, skipping empty entries."""
        return [c.strip() for c in self.scan_customers.split(",") if c.strip()]

    @property
    def active_llm_key(self) -> str | None:
        """The API key for the *currently selected* provider — or None if absent.

        offline mode needs no key, so returns a sentinel non-None string so the
        lifespan doesn't treat it as a misconfiguration.
        """
        if self.llm_provider == "offline":
            return "offline-no-key-needed"
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key
        return self.moonshot_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings accessor. Tests call `get_settings.cache_clear()` to reset."""
    return Settings()
