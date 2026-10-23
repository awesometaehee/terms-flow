"""DB·저장소가 떠 있는 compose 환경에서 실행한다: docker compose run --rm api pytest"""

from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_database_and_storage_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "storage": "ok"}
