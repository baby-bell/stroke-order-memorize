import pytest
from app.db import Database


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    database = Database(":memory:")
    yield database
    database.close()
