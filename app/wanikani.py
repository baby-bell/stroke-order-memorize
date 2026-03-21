import asyncio
import time
from collections.abc import Callable, Awaitable
from datetime import datetime, timezone

import httpx

from app.models import ResponseMeta, SyncMeta

_WANIKANI_BASE = "https://api.wanikani.com"


def make_client(
    api_key: str,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.AsyncClient:
    """Create a WaniKani API client with 1 RPS rate limiting."""
    lock = asyncio.Lock()
    last_request_time = [0.0]

    async def _rate_limit_hook(request: httpx.Request) -> None:
        async with lock:
            now = clock()
            elapsed = now - last_request_time[0]
            if elapsed < 1.0:
                await sleep(1.0 - elapsed)
                last_request_time[0] = clock()
            else:
                last_request_time[0] = now

    return httpx.AsyncClient(
        base_url=_WANIKANI_BASE,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Wanikani-Revision": "20170710",
        },
        event_hooks={"request": [_rate_limit_hook]},
    )


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    extra_headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> httpx.Response | None:
    """GET url with 429 retry (max 3 attempts). Returns None on 304, Response on success."""
    headers = extra_headers or {}
    for attempt in range(3):
        resp = await client.get(url, headers=headers, params=params)
        if resp.status_code == 304:
            return None
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        if attempt < 2:
            reset = resp.headers.get("RateLimit-Reset")
            if reset:
                wait = max(0.0, int(reset) - datetime.now(timezone.utc).timestamp())
            else:
                wait = 2.0**attempt
            await asyncio.sleep(wait)
    resp.raise_for_status()
    return resp  # type: ignore[return-value]


async def _paginate(client: httpx.AsyncClient, url: str) -> list[dict]:
    """Collect all items from a paginated WaniKani endpoint."""
    items: list[dict] = []
    next_url: str | None = url
    while next_url:
        resp = await _request_with_retry(client, next_url)
        assert resp is not None  # no conditional headers passed, so 304 won't occur
        body = resp.json()
        items.extend(body["data"])
        next_url = body["pages"]["next_url"]
    return items


async def _paginate_from_response(
    client: httpx.AsyncClient,
    first_resp: httpx.Response,
) -> list[dict]:
    """Continue paginating starting from an already-fetched first response."""
    body = first_resp.json()
    items: list[dict] = list(body["data"])
    next_url: str | None = body["pages"]["next_url"]
    while next_url:
        resp = await _request_with_retry(client, next_url)
        assert resp is not None
        body = resp.json()
        items.extend(body["data"])
        next_url = body["pages"]["next_url"]
    return items


async def fetch_user(client: httpx.AsyncClient) -> dict:
    """Return user info dict (contains 'username' and 'level')."""
    resp = await _request_with_retry(client, f"{_WANIKANI_BASE}/v2/user")
    assert resp is not None
    return resp.json()["data"]


async def fetch_subjects(
    client: httpx.AsyncClient,
    sync_meta: SyncMeta | None = None,
) -> tuple[dict[int, tuple[str, int]] | None, ResponseMeta | None]:
    """Fetch kanji subjects from WaniKani, respecting conditional request headers.

    Returns (level_map, response_meta) where:
    - level_map is {subject_id: (kanji, level)} or None on 304
    - response_meta is ResponseMeta or None on 304
    """
    cond_headers: dict[str, str] = {}
    if sync_meta:
        if sync_meta.etag:
            cond_headers["If-None-Match"] = sync_meta.etag
        if sync_meta.last_modified:
            cond_headers["If-Modified-Since"] = sync_meta.last_modified

    url = f"{_WANIKANI_BASE}/v2/subjects"
    params = {"types": "kanji"}
    if sync_meta:
        params["updated_after"] = sync_meta.synced_at

    first_resp = await _request_with_retry(
        client, url, extra_headers=cond_headers, params=params
    )

    if first_resp is None:
        return None, None

    items = await _paginate_from_response(client, first_resp)
    level_map = {
        item["id"]: (item["data"]["characters"], item["data"]["level"])
        for item in items
    }
    response_meta = ResponseMeta(
        etag=first_resp.headers.get("etag"),
        last_modified=first_resp.headers.get("last-modified"),
    )
    return level_map, response_meta


async def fetch_passed_assignments(
    client: httpx.AsyncClient,
    sync_meta: SyncMeta | None = None,
) -> tuple[list[int] | None, ResponseMeta | None]:
    """Fetch passed kanji assignments from WaniKani.

    Returns (passed_ids, response_meta) where:
    - passed_ids is [subject_id, ...] or None on 304
    - response_meta is ResponseMeta or None on 304
    """
    cond_headers: dict[str, str] = {}
    if sync_meta:
        if sync_meta.etag:
            cond_headers["If-None-Match"] = sync_meta.etag
        if sync_meta.last_modified:
            cond_headers["If-Modified-Since"] = sync_meta.last_modified

    url = f"{_WANIKANI_BASE}/v2/assignments"
    params = {"subject_type": "kanji", "passed_at": "true"}
    if sync_meta:
        params["updated_after"] = sync_meta.synced_at

    first_resp = await _request_with_retry(
        client, url, extra_headers=cond_headers, params=params
    )

    if first_resp is None:
        return None, None

    items = await _paginate_from_response(client, first_resp)
    passed_ids = [item["data"]["subject_id"] for item in items]
    response_meta = ResponseMeta(
        etag=first_resp.headers.get("etag"),
        last_modified=first_resp.headers.get("last-modified"),
    )
    return passed_ids, response_meta
