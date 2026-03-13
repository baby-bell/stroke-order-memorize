import asyncio
from datetime import datetime, timezone

import httpx

import app.db as db

_WANIKANI_BASE = "https://api.wanikani.com"


async def _request_with_retry(
    client: httpx.AsyncClient,
    url: str,
    extra_headers: dict[str, str] | None = None,
) -> httpx.Response | None:
    """GET url with 429 retry (max 3 attempts). Returns None on 304, Response on success."""
    headers = extra_headers or {}
    for attempt in range(3):
        resp = await client.get(url, headers=headers)
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


async def fetch_kanji_level_map(
    client: httpx.AsyncClient,
    updated_after: str | None = None,
) -> dict[int, tuple[str, int]]:
    """Return {subject_id: (character, level)} for all kanji subjects."""
    url = f"{_WANIKANI_BASE}/v2/subjects?types=kanji"
    if updated_after:
        url += f"&updated_after={updated_after}"
    items = await _paginate(client, url)
    return {
        item["id"]: (item["data"]["characters"], item["data"]["level"])
        for item in items
    }


async def fetch_passed_kanji(
    client: httpx.AsyncClient,
    updated_after: str | None = None,
) -> list[int]:
    """Return list of subject_ids for all passed kanji assignments."""
    url = f"{_WANIKANI_BASE}/v2/assignments?subject_type=kanji&passed_at=true"
    if updated_after:
        url += f"&updated_after={updated_after}"
    items = await _paginate(client, url)
    return [item["data"]["subject_id"] for item in items]


async def sync(client: httpx.AsyncClient) -> list[tuple[str, int]]:
    """
    Sync passed WaniKani kanji into the local DB.
    Returns list of (kanji, level) pairs that were processed.

    Uses updated_after and conditional requests (ETag/If-None-Match) to
    minimize API usage on repeat syncs.
    """
    now = datetime.now(timezone.utc).isoformat()

    # --- Subjects (kanji level map) ---
    subjects_meta = db.get_sync_meta("subjects")
    cond_headers: dict[str, str] = {}
    if subjects_meta:
        if subjects_meta["etag"]:
            cond_headers["If-None-Match"] = subjects_meta["etag"]
        if subjects_meta["last_modified"]:
            cond_headers["If-Modified-Since"] = subjects_meta["last_modified"]

    subjects_url = f"{_WANIKANI_BASE}/v2/subjects?types=kanji"
    if subjects_meta:
        subjects_url += f"&updated_after={subjects_meta['synced_at']}"

    first_resp = await _request_with_retry(client, subjects_url, extra_headers=cond_headers)

    if first_resp is None:  # 304 — nothing changed, use local cache
        level_map = db.get_cached_subjects()
    else:
        items = await _paginate_from_response(client, first_resp)
        new_subjects = {
            item["id"]: (item["data"]["characters"], item["data"]["level"])
            for item in items
        }
        db.upsert_cached_subjects(new_subjects)
        level_map = db.get_cached_subjects()
        db.set_sync_meta(
            "subjects",
            now,
            etag=first_resp.headers.get("etag"),
            last_modified=first_resp.headers.get("last-modified"),
        )

    # --- Assignments (passed kanji) ---
    assignments_meta = db.get_sync_meta("assignments")
    cond_headers = {}
    if assignments_meta:
        if assignments_meta["etag"]:
            cond_headers["If-None-Match"] = assignments_meta["etag"]
        if assignments_meta["last_modified"]:
            cond_headers["If-Modified-Since"] = assignments_meta["last_modified"]

    assignments_url = f"{_WANIKANI_BASE}/v2/assignments?subject_type=kanji&passed_at=true"
    if assignments_meta:
        assignments_url += f"&updated_after={assignments_meta['synced_at']}"

    first_resp = await _request_with_retry(client, assignments_url, extra_headers=cond_headers)

    if first_resp is None:  # 304 — nothing changed, skip processing
        return []

    items = await _paginate_from_response(client, first_resp)
    passed_ids = [item["data"]["subject_id"] for item in items]
    db.set_sync_meta(
        "assignments",
        now,
        etag=first_resp.headers.get("etag"),
        last_modified=first_resp.headers.get("last-modified"),
    )

    synced: list[tuple[str, int]] = []
    for subject_id in passed_ids:
        if subject_id not in level_map:
            continue
        kanji, level = level_map[subject_id]
        db.upsert_character(kanji, level, now)
        db.insert_card_if_new(kanji)
        synced.append((kanji, level))
    return synced
