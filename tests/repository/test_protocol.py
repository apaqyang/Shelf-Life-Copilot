"""Tests for the BatchRepository seam — the Open Core data-source boundary.

JsonRepository is the v0.1 default; enterprise ERP plugins swap themselves in
via set_repository so nothing downstream learns where batches came from.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from src.models import Batch, CustomerConfig
from src.repository import (
    BatchRepository,
    JsonRepository,
    get_repository,
    reset_repository,
    set_repository,
)


@pytest.fixture(autouse=True)
def _reset_active_repository() -> Iterator[None]:
    """Keep the module-level singleton from leaking across tests."""
    reset_repository()
    yield
    reset_repository()


@pytest.fixture
def temp_data_root(tmp_path: Path) -> Path:
    (tmp_path / "batches").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "batches" / "customerT.json").write_text(
        json.dumps(
            [
                {
                    "batch_id": "T-001",
                    "material_id": "M-T-001",
                    "material_name": "测试物料",
                    "production_date": "2026-04-01",
                    "expiry_date": "2026-07-01",
                    "stock_qty": 100.0,
                    "customer_id": "customerT",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "config" / "customerT.actions.json").write_text(
        json.dumps(
            {
                "customer_id": "customerT",
                "industry": "test",
                "enabled_actions": ["transform"],
                "industry_phrases": {"transform": "转加工"},
                "alert_thresholds": {"yellow": 30, "orange": 15, "red": 7},
                "decision_makers": ["userid_test"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


class TestJsonRepository:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(JsonRepository(), BatchRepository)

    def test_load_batches_uses_its_root(self, temp_data_root: Path) -> None:
        repo = JsonRepository(root=temp_data_root)
        batches = repo.load_batches("customerT")
        assert len(batches) == 1
        assert isinstance(batches[0], Batch)
        assert batches[0].batch_id == "T-001"

    def test_load_customer_config_uses_its_root(self, temp_data_root: Path) -> None:
        repo = JsonRepository(root=temp_data_root)
        config = repo.load_customer_config("customerT")
        assert isinstance(config, CustomerConfig)
        assert config.customer_id == "customerT"


class TestActiveRepositorySeam:
    def test_default_is_json_repository(self) -> None:
        assert isinstance(get_repository(), JsonRepository)

    def test_set_repository_overrides(self, temp_data_root: Path) -> None:
        override = JsonRepository(root=temp_data_root)
        set_repository(override)
        assert get_repository() is override

    def test_reset_restores_default(self, temp_data_root: Path) -> None:
        set_repository(JsonRepository(root=temp_data_root))
        reset_repository()
        got = get_repository()
        assert isinstance(got, JsonRepository)
        # default root, not the temp one — real mock data resolves
        assert got.load_customer_config("customerA").customer_id == "customerA"

    def test_a_fake_repository_satisfies_protocol(self) -> None:
        class FakeErpRepository:
            def load_batches(self, customer_id: str) -> list[Batch]:
                return []

            def load_customer_config(self, customer_id: str) -> CustomerConfig:
                raise NotImplementedError

        fake = FakeErpRepository()
        assert isinstance(fake, BatchRepository)
        set_repository(fake)
        assert get_repository() is fake
