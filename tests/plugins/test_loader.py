"""Tests for the enterprise plugin loader — the Open Core registration seam.

Open-source core ships with no plugins; paying customers drop private packages
into plugins/enterprise/<name>/. On startup the loader discovers them and calls
each package's register(registry). No plugins → pure open-source mode.
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest
from fastapi import FastAPI

from src.plugins import PluginRegistry, load_plugins
from src.runtime.config import Settings


def _write_plugin(enterprise_dir: Path, name: str, body: str) -> None:
    pkg = enterprise_dir / name
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text(textwrap.dedent(body), encoding="utf-8")


def _registry() -> PluginRegistry:
    return PluginRegistry(app=FastAPI(), settings=Settings(_env_file=None))  # type: ignore[call-arg]


class TestNoPlugins:
    def test_missing_root_returns_empty(self, tmp_path: Path) -> None:
        loaded = load_plugins(_registry(), plugins_root=tmp_path / "does-not-exist")
        assert loaded == []

    def test_empty_enterprise_dir_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "enterprise").mkdir()
        assert load_plugins(_registry(), plugins_root=tmp_path) == []


class TestLoading:
    def test_register_is_called_with_registry(self, tmp_path: Path) -> None:
        _write_plugin(
            tmp_path / "enterprise",
            "demo",
            """
            def register(registry):
                registry.app.state.touched_by = "demo"
            """,
        )
        registry = _registry()
        loaded = load_plugins(registry, plugins_root=tmp_path)
        assert loaded == ["demo"]
        assert registry.app.state.touched_by == "demo"

    def test_loads_multiple_plugins_sorted(self, tmp_path: Path) -> None:
        ent = tmp_path / "enterprise"
        for name in ("erp_sap", "wecom_realtime"):
            _write_plugin(ent, name, "def register(registry):\n    pass\n")
        loaded = load_plugins(_registry(), plugins_root=tmp_path)
        assert loaded == ["erp_sap", "wecom_realtime"]

    def test_plugin_without_register_is_skipped(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _write_plugin(tmp_path / "enterprise", "broken", "X = 1\n")
        caplog.set_level(logging.WARNING, logger="src.plugins.loader")
        loaded = load_plugins(_registry(), plugins_root=tmp_path)
        assert loaded == []
        assert any("register" in r.message for r in caplog.records)

    def test_non_package_dir_ignored(self, tmp_path: Path) -> None:
        ent = tmp_path / "enterprise"
        (ent / "notapkg").mkdir(parents=True)  # no __init__.py
        (ent / "notapkg" / "readme.txt").write_text("x", encoding="utf-8")
        assert load_plugins(_registry(), plugins_root=tmp_path) == []
