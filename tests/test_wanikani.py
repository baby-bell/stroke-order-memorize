from unittest.mock import AsyncMock, patch

import pytest
import respx
import httpx
from datetime import datetime, timezone
import app.db as db
from app.wanikani import (
    fetch_user,
    fetch_kanji_level_map,
    fetch_passed_kanji,
    sync,
    _request_with_retry,
)

BASE = "https://api.wanikani.com"

_SUBJECTS_PAGE = {
    "pages": {"next_url": None},
    "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
}
_ASSIGNMENTS_PAGE = {
    "pages": {"next_url": None},
    "data": [{"data": {"subject_id": 440}}],
}


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
async def test_fetch_kanji_level_map_appends_updated_after(wk_client):
    ts = "2024-01-01T00:00:00+00:00"
    respx.get(f"{BASE}/v2/subjects?types=kanji&updated_after={ts}").mock(
        return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []})
    )
    result = await fetch_kanji_level_map(wk_client, updated_after=ts)
    assert result == {}


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
async def test_fetch_passed_kanji_appends_updated_after(wk_client):
    ts = "2024-06-01T00:00:00+00:00"
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={ts}"
    ).mock(
        return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []})
    )
    result = await fetch_passed_kanji(wk_client, updated_after=ts)
    assert result == []


@respx.mock
@pytest.mark.asyncio
async def test_sync_upserts_characters_and_creates_cards(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
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
    db.upsert_character("一", 1, "2024-01-01T00:00:00+00:00")
    db.insert_card_if_new("一")
    db._conn.execute("UPDATE cards SET stability = 7.7 WHERE kanji = '一'")
    db._conn.commit()

    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
    )
    await sync(wk_client)
    row = db._conn.execute(
        "SELECT stability FROM cards WHERE kanji = '一'"
    ).fetchone()
    assert row["stability"] == 7.7  # unchanged


@respx.mock
@pytest.mark.asyncio
async def test_sync_stores_sync_meta_after_first_sync(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            headers={"ETag": '"subjects-etag"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
            json=_SUBJECTS_PAGE,
        )
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            headers={"ETag": '"assignments-etag"'},
            json=_ASSIGNMENTS_PAGE,
        )
    )
    await sync(wk_client)

    subjects_meta = db.get_sync_meta("subjects")
    assert subjects_meta is not None
    assert subjects_meta["etag"] == '"subjects-etag"'
    assert subjects_meta["last_modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"

    assignments_meta = db.get_sync_meta("assignments")
    assert assignments_meta is not None
    assert assignments_meta["etag"] == '"assignments-etag"'


@respx.mock
@pytest.mark.asyncio
async def test_sync_populates_subject_cache(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
    )
    await sync(wk_client)
    assert db.has_cached_subjects()
    assert db.get_cached_subjects() == {440: ("一", 1)}


@respx.mock
@pytest.mark.asyncio
async def test_sync_uses_updated_after_on_second_call(wk_client):
    """Second sync appends updated_after from stored sync_meta to both URLs."""
    prior_ts = "2024-01-01T00:00:00+00:00"
    db.set_sync_meta("subjects", prior_ts, etag='"old-subjects"')
    db.set_sync_meta("assignments", prior_ts, etag='"old-assignments"')
    db.upsert_cached_subjects({440: ("一", 1)})

    subjects_route = respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []}))
    assignments_route = respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE))

    await sync(wk_client)

    assert subjects_route.called
    assert assignments_route.called


@respx.mock
@pytest.mark.asyncio
async def test_sync_sends_conditional_headers_when_etag_stored(wk_client):
    """sync() sends If-None-Match when etag is in sync_meta."""
    prior_ts = "2024-01-01T00:00:00+00:00"
    db.set_sync_meta("subjects", prior_ts, etag='"my-etag"')
    db.set_sync_meta("assignments", prior_ts)
    db.upsert_cached_subjects({440: ("一", 1)})

    subjects_route = respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []}))
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE))

    await sync(wk_client)

    request = subjects_route.calls[0].request
    assert request.headers.get("if-none-match") == '"my-etag"'


@respx.mock
@pytest.mark.asyncio
async def test_sync_sends_if_modified_since_when_last_modified_stored(wk_client):
    prior_ts = "2024-01-01T00:00:00+00:00"
    lm = "Mon, 01 Jan 2024 00:00:00 GMT"
    db.set_sync_meta("subjects", prior_ts, last_modified=lm)
    db.set_sync_meta("assignments", prior_ts)
    db.upsert_cached_subjects({440: ("一", 1)})

    subjects_route = respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []}))
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE))

    await sync(wk_client)

    request = subjects_route.calls[0].request
    assert request.headers.get("if-modified-since") == lm


@respx.mock
@pytest.mark.asyncio
async def test_sync_304_for_subjects_loads_from_cache(wk_client):
    """When subjects endpoint returns 304, sync() uses subject_cache."""
    prior_ts = "2024-01-01T00:00:00+00:00"
    db.set_sync_meta("subjects", prior_ts, etag='"subjects-etag"')
    db.set_sync_meta("assignments", prior_ts)
    db.upsert_cached_subjects({440: ("一", 1)})

    respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(304))
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE))

    synced = await sync(wk_client)
    assert synced == [("一", 1)]


@respx.mock
@pytest.mark.asyncio
async def test_sync_304_for_assignments_returns_empty(wk_client):
    """When assignments endpoint returns 304, sync() skips processing and returns []."""
    prior_ts = "2024-01-01T00:00:00+00:00"
    db.set_sync_meta("subjects", prior_ts, etag='"subjects-etag"')
    db.set_sync_meta("assignments", prior_ts, etag='"assignments-etag"')
    db.upsert_cached_subjects({440: ("一", 1)})

    respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(304))
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(304))

    synced = await sync(wk_client)
    assert synced == []


@respx.mock
@pytest.mark.asyncio
async def test_sync_full_round_trip_second_sync_uses_cache(wk_client):
    """First sync populates cache; second sync hits 304 and uses it."""
    # First sync: full fetch
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            headers={"ETag": '"s-etag"'},
            json=_SUBJECTS_PAGE,
        )
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            headers={"ETag": '"a-etag"'},
            json=_ASSIGNMENTS_PAGE,
        )
    )
    synced1 = await sync(wk_client)
    assert synced1 == [("一", 1)]
    assert db.has_cached_subjects()

    # Second sync: 304 for both endpoints
    prior_ts = db.get_sync_meta("subjects")["synced_at"]
    respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(304))
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior_ts}"
    ).mock(return_value=httpx.Response(304))

    synced2 = await sync(wk_client)
    assert synced2 == []


@pytest.mark.asyncio
async def test_request_with_retry_retries_on_429(wk_client):
    """_request_with_retry retries on 429 and succeeds on subsequent attempt."""
    call_count = 0

    async def handler(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(429, headers={"RateLimit-Reset": "0"})
        return httpx.Response(200, json={"ok": True})

    with respx.mock:
        respx.get(f"{BASE}/v2/user").mock(side_effect=handler)
        with patch("app.wanikani.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            resp = await _request_with_retry(wk_client, f"{BASE}/v2/user")
        assert resp is not None
        assert resp.status_code == 200
        assert call_count == 2
        mock_sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_request_with_retry_raises_after_max_retries(wk_client):
    """_request_with_retry raises HTTPStatusError after 3 consecutive 429s."""
    with respx.mock:
        respx.get(f"{BASE}/v2/user").mock(
            return_value=httpx.Response(429, headers={"RateLimit-Reset": "0"})
        )
        with patch("app.wanikani.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await _request_with_retry(wk_client, f"{BASE}/v2/user")


@pytest.mark.asyncio
async def test_request_with_retry_returns_none_on_304(wk_client):
    with respx.mock:
        respx.get(f"{BASE}/v2/user").mock(return_value=httpx.Response(304))
        result = await _request_with_retry(wk_client, f"{BASE}/v2/user")
    assert result is None
