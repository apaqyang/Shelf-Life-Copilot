"""Tests for the JSON repository loaders — both unit tests and real mock data smoke."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.models import ActionType, Batch, CustomerConfig
from src.repository import DEFAULT_DATA_ROOT, load_batches, load_customer_config


@pytest.fixture
def temp_data_root(tmp_path: Path) -> Path:
    """A tmp data root with one minimal batch + one minimal customer config."""
    (tmp_path / "batches").mkdir()
    (tmp_path / "config").mkdir()

    batches_payload = [
        {
            "batch_id": "T-001",
            "material_id": "M-T-001",
            "material_name": "测试物料",
            "production_date": "2026-04-01",
            "expiry_date": "2026-07-01",
            "stock_qty": 100.0,
            "customer_id": "customerT",
        }
    ]
    (tmp_path / "batches" / "customerT.json").write_text(
        json.dumps(batches_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    config_payload = {
        "customer_id": "customerT",
        "industry": "test",
        "enabled_actions": ["transform"],
        "industry_phrases": {"transform": "转加工"},
        "alert_thresholds": {"yellow": 30, "orange": 15, "red": 7},
        "decision_makers": ["userid_test"],
    }
    (tmp_path / "config" / "customerT.actions.json").write_text(
        json.dumps(config_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    return tmp_path


class TestLoadCustomerConfig:
    def test_parses_config_from_tmp_root(self, temp_data_root: Path) -> None:
        config = load_customer_config("customerT", root=temp_data_root)
        assert isinstance(config, CustomerConfig)
        assert config.customer_id == "customerT"
        assert ActionType.TRANSFORM in config.enabled_actions

    def test_missing_file_raises_filenotfound(self, temp_data_root: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_customer_config("nonexistent", root=temp_data_root)


class TestLoadBatches:
    def test_parses_batches_from_tmp_root(self, temp_data_root: Path) -> None:
        batches = load_batches("customerT", root=temp_data_root)
        assert len(batches) == 1
        assert isinstance(batches[0], Batch)
        assert batches[0].batch_id == "T-001"

    def test_missing_file_raises_filenotfound(self, temp_data_root: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_batches("nonexistent", root=temp_data_root)


class TestRealMockData:
    """Smoke tests against the actual mock JSON files shipped in `data/`."""

    def test_default_data_root_exists(self) -> None:
        assert DEFAULT_DATA_ROOT.is_dir(), f"Mock data root missing: {DEFAULT_DATA_ROOT}"

    def test_customer_a_config_loads(self) -> None:
        config = load_customer_config("customerA")
        assert config.customer_id == "customerA"
        assert config.industry == "frozen_seafood"
        assert ActionType.EMPLOYEE_CANTEEN in config.disabled_actions
        assert config.alert_thresholds.yellow == 30
        # 150万/年 ÷ 180 批次 ≈ 8333
        assert config.avg_savings_per_batch == 8333

    def test_customer_b_config_loads_with_tighter_thresholds(self) -> None:
        config = load_customer_config("customerB")
        assert config.customer_id == "customerB"
        assert config.industry == "prepared_meals"
        assert ActionType.TRANSFORM in config.disabled_actions
        assert config.alert_thresholds.yellow == 14
        assert config.alert_thresholds.red == 3
        # 86万/年 ÷ 350 批次 ≈ 2457
        assert config.avg_savings_per_batch == 2457

    def test_customer_a_batches_load(self) -> None:
        batches = load_batches("customerA")
        assert len(batches) >= 5
        assert all(b.customer_id == "customerA" for b in batches)
        material_names = {b.material_name for b in batches}
        assert "冷冻虾仁" in material_names

    def test_customer_b_batches_load(self) -> None:
        batches = load_batches("customerB")
        assert len(batches) >= 5
        assert all(b.customer_id == "customerB" for b in batches)
        assert all(b.unit == "盒" for b in batches)
