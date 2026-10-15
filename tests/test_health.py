from fastapi.testclient import TestClient

from codechef_task.app import app
from codechef_task.database import get_db_session


def test_health_does_not_require_database() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_database_health_success() -> None:
    class FakeSession:
        async def execute(self, statement: object) -> None:
            assert str(statement) == "SELECT 1"

    async def provide_session():
        yield FakeSession()

    app.dependency_overrides[get_db_session] = provide_session
    try:
        with TestClient(app) as client:
            response = client.get("/health/db")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "database": "available"}


def test_database_health_failure_is_generic() -> None:
    class FakeSession:
        async def execute(self, statement: object) -> None:
            raise RuntimeError("private connection detail")

    async def provide_session():
        yield FakeSession()

    app.dependency_overrides[get_db_session] = provide_session
    try:
        with TestClient(app) as client:
            response = client.get("/health/db")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "detail": {"status": "unhealthy", "database": "unavailable"}
    }
    assert "private connection detail" not in response.text
