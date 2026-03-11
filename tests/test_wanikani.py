import pytest
import respx
import httpx
from datetime import datetime, timezone
import app.db as db
from app.wanikani import fetch_user, fetch_kanji_level_map, fetch_passed_kanji, sync

BASE = "https://api.wanikani.com"


@pytest.fixture
def wk_client():
    return httpx.AsyncClient(
        base_url=BASE,
        headers={"Authorization": "Bearer test-key"},
    )


@respx.mock
@pytest.mark.asyncio
async def test_fetch_user(wk_client):
    respx.get(f"{BASE}/v2/user").mock(
        return_value=httpx.Response(
            200, json={"data": {"username": "testuser", "level": 5}}
        )
    )
    result = await fetch_user(wk_client)
    assert result["username"] == "testuser"
    assert result["level"] == 5


@respx.mock
@pytest.mark.asyncio
async def test_fetch_kanji_level_map_single_page(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [
                    {"id": 440, "data": {"characters": "一", "level": 1}},
                    {"id": 441, "data": {"characters": "二", "level": 1}},
                ],
            },
        )
    )
    result = await fetch_kanji_level_map(wk_client)
    assert result == {440: ("一", 1), 441: ("二", 1)}


@respx.mock
@pytest.mark.asyncio
async def test_fetch_kanji_level_map_follows_pagination(wk_client):
    page2_url = f"{BASE}/v2/subjects?page_after_id=440"
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": page2_url},
                "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
            },
        )
    )
    respx.get(page2_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"id": 441, "data": {"characters": "二", "level": 1}}],
            },
        )
    )
    result = await fetch_kanji_level_map(wk_client)
    assert 440 in result and 441 in result


@respx.mock
@pytest.mark.asyncio
async def test_fetch_passed_kanji(wk_client):
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [
                    {"data": {"subject_id": 440}},
                    {"data": {"subject_id": 441}},
                ],
            },
        )
    )
    result = await fetch_passed_kanji(wk_client)
    assert result == [440, 441]


@respx.mock
@pytest.mark.asyncio
async def test_sync_upserts_characters_and_creates_cards(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
            },
        )
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"data": {"subject_id": 440}}],
            },
        )
    )
    synced = await sync(wk_client)
    assert synced == [("一", 1)]
    char_row = db._conn.execute(
        "SELECT wk_level FROM characters WHERE kanji = '一'"
    ).fetchone()
    assert char_row["wk_level"] == 1
    card_row = db._conn.execute(
        "SELECT kanji FROM cards WHERE kanji = '一'"
    ).fetchone()
    assert card_row is not None


@respx.mock
@pytest.mark.asyncio
async def test_sync_does_not_overwrite_existing_card_state(wk_client):
    # Pre-populate a card with FSRS state
    db.upsert_character("一", 1, "2024-01-01T00:00:00+00:00")
    db.insert_card_if_new("一")
    db._conn.execute("UPDATE cards SET stability = 7.7 WHERE kanji = '一'")
    db._conn.commit()

    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
            },
        )
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"data": {"subject_id": 440}}],
            },
        )
    )
    await sync(wk_client)
    row = db._conn.execute(
        "SELECT stability FROM cards WHERE kanji = '一'"
    ).fetchone()
    assert row["stability"] == 7.7  # unchanged
