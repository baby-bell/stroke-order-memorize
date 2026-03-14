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


@pytest.mark.asyncio
async def test_sync_without_api_key_returns_error_partial(client):
    # No WANIKANI_API_KEY set in test environment
    resp = await client.post("/sync")
    assert resp.status_code == 200  # HTMX expects 200
    assert "WANIKANI_API_KEY" in resp.text or "error" in resp.text.lower()


@pytest.mark.asyncio
async def test_session_redirects_to_done_when_no_due_cards(client):
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/done")


@pytest.mark.asyncio
async def test_session_redirects_to_card_when_cards_due(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/card")


@pytest.mark.asyncio
async def test_session_card_displays_kanji(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert resp.status_code == 200
    assert "一" in resp.text


@pytest.mark.asyncio
async def test_session_strokes_returns_svg_paths(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/strokes")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "<path" in resp.text


@pytest.mark.asyncio
async def test_session_review_valid_rating_advances_queue(client):
    for kanji in ["一", "二"]:
        db.upsert_character(kanji, 1, now_iso())
        db.insert_card_if_new(kanji)
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    # FSRS review row inserted
    row = db._conn.execute("SELECT COUNT(*) FROM reviews").fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_session_review_last_card_triggers_hx_redirect(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    assert resp.headers.get("hx-redirect", "").endswith("/session/done")


@pytest.mark.asyncio
async def test_session_done_returns_200(client):
    resp = await client.get("/session/done")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_home_shows_new_count(client, monkeypatch):
    import app.routes as routes
    monkeypatch.setattr(routes, "_NEW_CARDS_PER_DAY", 1)
    for kanji in ["一", "二", "三"]:
        db.upsert_character(kanji, 1, now_iso())
        db.insert_card_if_new(kanji)
    resp = await client.get("/")
    assert "1 new" in resp.text
