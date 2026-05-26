"""Pytest 全局 fixtures。"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from src.main import app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a TestClient bound to the FastAPI app."""
    with TestClient(app) as test_client:
        yield test_client
