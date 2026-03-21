import re

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from app.db import Database
from app.routes import get_db


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest_asyncio.fixture
async def client(fresh_db, monkeypatch):
    # Prevent the lifespan from creating a real database file on disk.
    monkeypatch.setenv("DB_PATH", ":memory:")

    from main import app

    app.dependency_overrides[get_db] = lambda: fresh_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()


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
async def test_session_redirects_to_card_when_cards_due(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/card")


@pytest.mark.asyncio
async def test_session_card_displays_kanji(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert resp.status_code == 200
    assert "一" in resp.text


@pytest.mark.asyncio
async def test_session_strokes_returns_svg_paths(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/strokes")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "<path" in resp.text


@pytest.mark.asyncio
async def test_session_review_valid_rating_advances_queue(client, fresh_db):
    for kanji in ["一", "二"]:
        fresh_db.upsert_character(kanji, 1, now_iso())
        fresh_db.insert_card_if_new(kanji)
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    # FSRS review row inserted
    row = fresh_db.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_session_review_last_card_triggers_hx_redirect(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    assert resp.headers.get("hx-redirect", "").endswith("/session/done")


@pytest.mark.asyncio
async def test_session_done_returns_200(client):
    resp = await client.get("/session/done")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_home_shows_new_count(client, fresh_db, monkeypatch):
    import app.routes as routes

    monkeypatch.setattr(routes, "_NEW_CARDS_PER_DAY", 1)
    for kanji in ["一", "二", "三"]:
        fresh_db.upsert_character(kanji, 1, now_iso())
        fresh_db.insert_card_if_new(kanji)
    resp = await client.get("/")
    assert "1 new" in resp.text


@pytest.mark.asyncio
async def test_session_review_again_requeues_card(client, fresh_db):
    """Rating 'Again' should re-insert the card into the session queue."""
    for kanji in ["一", "二", "三"]:
        fresh_db.upsert_character(kanji, 1, now_iso())
        fresh_db.insert_card_if_new(kanji)
    await client.get("/session", follow_redirects=True)

    # Rate first card "Again"
    resp = await client.post("/session/review", data={"rating": "1"})
    assert resp.status_code == 200

    # The session should not be done yet
    assert "hx-redirect" not in resp.headers

    # Walk through remaining cards rating "Good" and collect all kanji seen
    seen = []
    for _ in range(10):  # safety limit
        resp_card = await client.get("/session/card")
        if resp_card.status_code != 200 or "kanji-display" not in resp_card.text:
            break
        match = re.search(r'class="kanji-display"[^>]*>(.+?)</div>', resp_card.text)
        if match:
            seen.append(match.group(1))
        resp = await client.post("/session/review", data={"rating": "3"})
        if resp.headers.get("hx-redirect"):
            break

    # With 3 cards and 1 "Again", we should see at least 3 cards in the loop
    # (2 remaining + 1 requeued). Without requeue we'd only see 2.
    assert len(seen) >= 3, f"Expected requeued card to appear again, saw: {seen}"


@pytest.mark.asyncio
async def test_session_card_has_go_home_link(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert 'href="/"' in resp.text
    assert "Go Home" in resp.text


@pytest.mark.asyncio
async def test_session_card_show_strokes_has_id(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert 'id="show-strokes-btn"' in resp.text


@pytest.mark.asyncio
async def test_session_strokes_has_prev_button(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/strokes")
    assert 'id="prev-stroke-btn"' in resp.text
    assert "prevStroke()" in resp.text


@pytest.mark.asyncio
async def test_session_review_continues_when_cards_become_due_during_session(
    client, fresh_db, monkeypatch
):
    """When the queue empties but cards are now due again, session should continue."""
    from fsrs import Card, State

    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)

    # Make schedule_review return a card that's immediately due again
    import app.routes as routes_mod
    from app.core import schedule_review as original_schedule

    def schedule_immediately_due(card, rating):
        updated = original_schedule(card, rating)
        # Force the card to be due right now (simulates short FSRS interval)
        updated = Card(
            state=updated.state,
            step=updated.step,
            stability=updated.stability,
            difficulty=updated.difficulty,
            due=datetime.now(timezone.utc),
            last_review=updated.last_review,
        )
        return updated

    monkeypatch.setattr(routes_mod, "schedule_review", schedule_immediately_due)

    # Review the only card with "Good" — queue empties, but card is immediately due
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    # Session should NOT end — the card is due again
    assert (
        "hx-redirect" not in resp.headers
    ), "Session ended despite cards being immediately due"


_SUBJECTS_PAGE = {
    "pages": {"next_url": None},
    "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
}
_ASSIGNMENTS_PAGE = {
    "pages": {"next_url": None},
    "data": [{"data": {"subject_id": 440}}],
}

BASE = "https://api.wanikani.com"


@respx.mock
@pytest.mark.asyncio
async def test_sync_creates_characters_and_cards(client, fresh_db, monkeypatch):
    monkeypatch.setenv("WANIKANI_API_KEY", "test-key")
    respx.get(url__startswith=f"{BASE}/v2/subjects").mock(
        return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
    )
    respx.get(url__startswith=f"{BASE}/v2/assignments").mock(
        return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
    )
    resp = await client.post("/sync")
    assert resp.status_code == 200
    assert "1 kanji" in resp.text
    # Verify DB side effects
    char_row = fresh_db.conn.execute(
        "SELECT wk_level FROM characters WHERE kanji = '一'"
    ).fetchone()
    assert char_row["wk_level"] == 1
    card_row = fresh_db.conn.execute(
        "SELECT kanji FROM cards WHERE kanji = '一'"
    ).fetchone()
    assert card_row is not None
