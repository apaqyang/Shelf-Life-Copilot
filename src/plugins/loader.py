"""Enterprise plugin discovery — the Open Core registration seam.

The open-source core ships with **no** enterprise plugins. Paying customers
drop private packages (shipped from a separate private repo / wheel) into
`plugins/enterprise/<name>/`, each exposing a top-level `register(registry)`.
On startup `load_plugins` discovers them and calls each `register`, letting a
plugin mount routers, override the BatchRepository, install AES WebhookCrypto,
etc. — all without forking the core.

If `plugins/enterprise/` is absent or empty, the service runs in pure
open-source mode. Making that the graceful default is this module's whole job.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType

from src.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)

# src/plugins/loader.py → parents[2] == repo root → repo-root/plugins
DEFAULT_PLUGINS_ROOT = Path(__file__).resolve().parents[2] / "plugins"


def _import_package(name: str, init_path: Path) -> ModuleType | None:
    """Import a plugin package from its __init__.py path, or None on failure."""
    module_name = f"sl_enterprise_plugin_{name}"
    spec = importlib.util.spec_from_file_location(module_name, init_path)
    if spec is None or spec.loader is None:  # pragma: no cover - importlib edge case
        logger.warning("Could not build import spec for plugin %r at %s", name, init_path)
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_plugins(
    registry: PluginRegistry,
    plugins_root: Path | None = None,
) -> list[str]:
    """Discover plugins/enterprise/<name>/ packages and call each register().

    Returns the names of plugins whose register() ran, in sorted order.
    """
    root = plugins_root if plugins_root is not None else DEFAULT_PLUGINS_ROOT
    enterprise = root / "enterprise"
    if not enterprise.is_dir():
        return registry.loaded

    for child in sorted(enterprise.iterdir()):
        init_path = child / "__init__.py"
        if not child.is_dir() or not init_path.is_file():
            continue
        module = _import_package(child.name, init_path)
        if module is None:  # pragma: no cover - paired with the importlib edge case above
            continue
        register = getattr(module, "register", None)
        if not callable(register):
            logger.warning("Plugin %r has no register(registry) function; skipping.", child.name)
            continue
        register(registry)
        registry.loaded.append(child.name)

    return registry.loaded
