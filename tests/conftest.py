import pytest
import app.db as db


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    db.init(":memory:")
    yield
    if db._conn:
        db._conn.close()
        db._conn = None
