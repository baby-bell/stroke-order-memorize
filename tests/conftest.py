import pytest
from app.db import Database


@pytest.fixture(autouse=True)
def _no_real_api_key(monkeypatch):
    """Prevent tests from accidentally using a real WaniKani API key."""
    monkeypatch.delenv("WANIKANI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    database = Database(":memory:")
    yield database
    database.close()
