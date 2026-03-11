import pytest
import app.db as db


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    db.init(":memory:")
    db.set_new_cards_per_day(20)
    yield
    if db._conn:
        db._conn.close()
        db._conn = None
