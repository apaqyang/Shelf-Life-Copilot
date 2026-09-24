from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.admin import router


def test_admin_console_is_static_shell_without_credentials() -> None:
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/admin")
    assert response.status_code == 200
    assert "多租户运营台" in response.text
    assert "Bearer token" in response.text
