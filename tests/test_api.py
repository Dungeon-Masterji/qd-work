import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


class PendingCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        pass

    def fetchall(self):
        return [
            (
                "ops-1",
                "R003",
                "approval",
                120,
                "Ledger owes 120",
                None,
            )
        ]


class PendingConnection:
    def cursor(self):
        return PendingCursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False
    def close(self):
        pass


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setattr(
        "app.api.routes.connection",
        lambda request: PendingConnection(),
    )
    monkeypatch.setattr(
        "app.main.run_migrations",
        lambda: None,
    )
    monkeypatch.setattr(
        "app.main.psycopg.connect",
        lambda url: PendingConnection(),
    )
    monkeypatch.setattr(
        "app.main.seed_if_empty",
        lambda connection: None,
    )
    with TestClient(app) as test_client:
        yield test_client


def test_pending_shape(client):
    response = client.get("/ops/pending")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "ops-1"
    assert response.json()[0]["amount"] == 120
