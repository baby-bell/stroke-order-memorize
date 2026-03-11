from datetime import datetime, timezone

import httpx

import app.db as db

_WANIKANI_BASE = "https://api.wanikani.com"


async def _paginate(client: httpx.AsyncClient, url: str) -> list[dict]:
    """Collect all items from a paginated WaniKani endpoint."""
    items: list[dict] = []
    next_url: str | None = url
    while next_url:
        resp = await client.get(next_url)
        resp.raise_for_status()
        body = resp.json()
        items.extend(body["data"])
        next_url = body["pages"]["next_url"]
    return items


async def fetch_user(client: httpx.AsyncClient) -> dict:
    """Return user info dict (contains 'username' and 'level')."""
    resp = await client.get(f"{_WANIKANI_BASE}/v2/user")
    resp.raise_for_status()
    return resp.json()["data"]


async def fetch_kanji_level_map(
    client: httpx.AsyncClient,
) -> dict[int, tuple[str, int]]:
    """Return {subject_id: (character, level)} for all kanji subjects."""
    items = await _paginate(client, f"{_WANIKANI_BASE}/v2/subjects?types=kanji")
    return {
        item["id"]: (item["data"]["characters"], item["data"]["level"])
        for item in items
    }


async def fetch_passed_kanji(client: httpx.AsyncClient) -> list[int]:
    """Return list of subject_ids for all passed kanji assignments."""
    items = await _paginate(
        client,
        f"{_WANIKANI_BASE}/v2/assignments?subject_type=kanji&passed_at=true",
    )
    return [item["data"]["subject_id"] for item in items]


async def sync(client: httpx.AsyncClient) -> list[tuple[str, int]]:
    """
    Sync passed WaniKani kanji into the local DB.
    Returns list of (kanji, level) pairs that were processed.
    """
    level_map = await fetch_kanji_level_map(client)
    passed_ids = await fetch_passed_kanji(client)
    now = datetime.now(timezone.utc).isoformat()
    synced: list[tuple[str, int]] = []
    for subject_id in passed_ids:
        if subject_id not in level_map:
            continue
        kanji, level = level_map[subject_id]
        db.upsert_character(kanji, level, now)
        db.insert_card_if_new(kanji)
        synced.append((kanji, level))
    return synced
