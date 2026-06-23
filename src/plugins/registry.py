"""PluginRegistry — what an enterprise plugin's `register()` receives.

Carries the live FastAPI app (to mount routers / set app.state) and the runtime
Settings (for plugin config). A plugin can also reach the repository / webhook
crypto seams directly via `src.repository.set_repository` /
`src.webhook.set_webhook_crypto`; the registry only needs to expose what a
plugin can't import for itself — the running app and its settings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import FastAPI

from src.runtime.config import Settings


@dataclass
class PluginRegistry:
    """Handed to each enterprise plugin's `register(registry)` entry point."""

    app: FastAPI
    settings: Settings
    loaded: list[str] = field(default_factory=list)
