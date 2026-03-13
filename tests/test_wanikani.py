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
    fetch_subjects,
    fetch_passed_assignments,
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
async def test_fetch_subjects_returns_level_map(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            headers={"ETag": '"s-etag"', "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
            json=_SUBJECTS_PAGE,
        )
    )
    level_map, meta = await fetch_subjects(wk_client)
    assert level_map == {440: ("一", 1)}
    assert meta["etag"] == '"s-etag"'
    assert meta["last_modified"] == "Mon, 01 Jan 2024 00:00:00 GMT"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_subjects_returns_none_on_304(wk_client):
    prior = {"synced_at": "2024-01-01T00:00:00+00:00", "etag": '"old"', "last_modified": None}
    respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior['synced_at']}"
    ).mock(return_value=httpx.Response(304))
    level_map, meta = await fetch_subjects(wk_client, sync_meta=prior)
    assert level_map is None
    assert meta is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_subjects_sends_conditional_headers(wk_client):
    prior = {
        "synced_at": "2024-01-01T00:00:00+00:00",
        "etag": '"my-etag"',
        "last_modified": "Mon, 01 Jan 2024 00:00:00 GMT",
    }
    route = respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior['synced_at']}"
    ).mock(return_value=httpx.Response(200, json=_SUBJECTS_PAGE))
    await fetch_subjects(wk_client, sync_meta=prior)
    request = route.calls[0].request
    assert request.headers.get("if-none-match") == '"my-etag"'
    assert request.headers.get("if-modified-since") == "Mon, 01 Jan 2024 00:00:00 GMT"


@respx.mock
@pytest.mark.asyncio
async def test_fetch_subjects_appends_updated_after(wk_client):
    prior = {"synced_at": "2024-01-01T00:00:00+00:00", "etag": None, "last_modified": None}
    route = respx.get(
        f"{BASE}/v2/subjects?types=kanji&updated_after={prior['synced_at']}"
    ).mock(return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []}))
    await fetch_subjects(wk_client, sync_meta=prior)
    assert route.called


@respx.mock
@pytest.mark.asyncio
async def test_fetch_passed_assignments_returns_ids(wk_client):
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            headers={"ETag": '"a-etag"'},
            json=_ASSIGNMENTS_PAGE,
        )
    )
    ids, meta = await fetch_passed_assignments(wk_client)
    assert ids == [440]
    assert meta["etag"] == '"a-etag"'


@respx.mock
@pytest.mark.asyncio
async def test_fetch_passed_assignments_returns_none_on_304(wk_client):
    prior = {"synced_at": "2024-01-01T00:00:00+00:00", "etag": '"old"', "last_modified": None}
    respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior['synced_at']}"
    ).mock(return_value=httpx.Response(304))
    ids, meta = await fetch_passed_assignments(wk_client, sync_meta=prior)
    assert ids is None
    assert meta is None


@respx.mock
@pytest.mark.asyncio
async def test_fetch_passed_assignments_sends_conditional_headers(wk_client):
    prior = {
        "synced_at": "2024-01-01T00:00:00+00:00",
        "etag": '"a-etag"',
        "last_modified": "Wed, 01 Jan 2025 00:00:00 GMT",
    }
    route = respx.get(
        f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true&updated_after={prior['synced_at']}"
    ).mock(return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE))
    await fetch_passed_assignments(wk_client, sync_meta=prior)
    request = route.calls[0].request
    assert request.headers.get("if-none-match") == '"a-etag"'
    assert request.headers.get("if-modified-since") == "Wed, 01 Jan 2025 00:00:00 GMT"


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
