import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
import app.db as db
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest_asyncio.fixture
async def client():
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_home_returns_200(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "stroke" in resp.text.lower()
