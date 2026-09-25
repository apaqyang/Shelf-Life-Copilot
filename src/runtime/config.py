"""Runtime Settings — pydantic-settings reads `.env` + environment.

Single source of truth for the long-running uvicorn process. CLI tools and
short-lived scripts still take their own args; this exists so a deployed
service has one well-typed config object, not scattered `os.environ.get`s.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    api_token: SecretStr | None = None
    api_token_customers: str = ""
    webhook_replay_window_seconds: int = 300
    max_request_body_bytes: int = 65_536
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    scan_concurrency: int = 4
    task_queue_enabled: bool = True
    task_worker_max_attempts: int = 3
    task_worker_poll_seconds: float = 0.2
    task_visibility_timeout_seconds: int = 300

    # ── persistence / output ──────────────────────────────────────────────
    persistence_backend: Literal["sqlite", "postgres"] = "sqlite"
    decisions_db_path: Path = Path("data/decisions.db")
    postgres_dsn: SecretStr | None = None
    postgres_pool_min_size: int = 1
    postgres_pool_max_size: int = 10
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
    llm_provider: Literal["anthropic", "moonshot", "local", "offline"] = "anthropic"
    anthropic_api_key: str | None = None
    moonshot_api_key: str | None = None
    local_llm_base_url: str = "http://127.0.0.1:11434/v1"
    local_llm_model: str = "local-model"
    local_llm_api_key: str = "local"

    # Optional operational override; normally read from each CustomerConfig.
    customer_baselines: dict[str, float] = Field(default_factory=dict)

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

    @field_validator(
        "webhook_replay_window_seconds",
        "max_request_body_bytes",
        "rate_limit_requests",
        "rate_limit_window_seconds",
        "scan_concurrency",
        "task_worker_max_attempts",
        "task_visibility_timeout_seconds",
        "postgres_pool_min_size",
        "postgres_pool_max_size",
    )
    @classmethod
    def _validate_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("security limits must be positive")
        return v

    @field_validator("task_worker_poll_seconds")
    @classmethod
    def _validate_positive_float(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("task worker poll interval must be positive")
        return v

    @model_validator(mode="after")
    def _validate_persistence(self) -> Settings:
        if self.persistence_backend == "postgres" and self.postgres_dsn is None:
            raise ValueError("POSTGRES_DSN is required when PERSISTENCE_BACKEND=postgres")
        if self.postgres_pool_min_size > self.postgres_pool_max_size:
            raise ValueError("POSTGRES_POOL_MIN_SIZE must not exceed POSTGRES_POOL_MAX_SIZE")
        return self

    @property
    def is_development(self) -> bool:
        return self.app_env.casefold() in {"development", "dev", "local", "test", "testing"}

    @property
    def scan_customers_list(self) -> list[str]:
        """Comma-separated SCAN_CUSTOMERS → list, skipping empty entries."""
        return [c.strip() for c in self.scan_customers.split(",") if c.strip()]

    @property
    def api_token_customer_ids(self) -> frozenset[str]:
        configured = [c.strip() for c in self.api_token_customers.split(",") if c.strip()]
        return frozenset(configured or self.scan_customers_list)

    @property
    def active_llm_key(self) -> str | None:
        """The API key for the *currently selected* provider — or None if absent.

        offline mode needs no key, so returns a sentinel non-None string so the
        lifespan doesn't treat it as a misconfiguration.
        """
        if self.llm_provider in {"offline", "local"}:
            return "offline-no-key-needed"
        if self.llm_provider == "anthropic":
            return self.anthropic_api_key
        return self.moonshot_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached Settings accessor. Tests call `get_settings.cache_clear()` to reset."""
    return Settings()
