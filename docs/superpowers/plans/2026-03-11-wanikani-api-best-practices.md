# WaniKani API Client Best-Practices Compliance

## Context

The WaniKani API client in `app/wanikani.py` works correctly but doesn't follow several API best practices. Every sync fetches **all** kanji subjects and **all** passed assignments from scratch, which is wasteful and risks hitting the 60 req/min rate limit for high-level users. The client also lacks local content caching, retry logic, revision pinning, and proper error differentiation.

The WaniKani API best practices recommend:
- **Cache subjects aggressively** — they rarely change and are expensive to fetch (many pages).
- **Cache reviews/resets long-term** — they're immutable after creation.
- **Use conditional requests** (`If-None-Match` / `If-Modified-Since`) to validate cached data without re-downloading.
- **Use `updated_after`** for incremental updates on collection endpoints.
- **Store `ETag` and `Last-Modified` headers** from responses and send them back on subsequent requests.

## Files to modify

- `app/wanikani.py` — main changes (client logic)
- `app/db.py` — add sync metadata table (timestamps, ETags, Last-Modified) and subject cache table
- `app/routes.py` — minor: pass revision header, surface better errors
- `tests/test_wanikani.py` — update/add tests

## Plan

### 1. Add cache and sync tables to `app/db.py`

#### a. `sync_meta` — per-endpoint sync state

```sql
CREATE TABLE IF NOT EXISTS sync_meta (
    endpoint        TEXT NOT NULL PRIMARY KEY,
    synced_at       TEXT NOT NULL,
    etag            TEXT,
    last_modified   TEXT
);
```

Add helpers:
- `get_sync_meta(endpoint) -> dict | None` — returns `{"synced_at", "etag", "last_modified"}`.
- `set_sync_meta(endpoint, timestamp, etag=None, last_modified=None)`.

#### b. `subject_cache` — locally cached kanji subjects

Subjects rarely change and are expensive to fetch (many pages of pagination). Cache them locally so subsequent syncs can skip the subjects endpoint entirely when an ETag/conditional request returns 304.

Column names mirror the API response structure: `id` is the top-level resource ID, `characters` and `level` live inside `data`.

```sql
CREATE TABLE IF NOT EXISTS subject_cache (
    id          INTEGER NOT NULL PRIMARY KEY,  -- top-level "id" field
    characters  TEXT NOT NULL,                  -- data.characters
    level       INTEGER NOT NULL               -- data.level
);
```

Add helpers:
- `get_cached_subjects() -> dict[int, tuple[str, int]]` — returns `{id: (characters, level)}` from cache.
- `upsert_cached_subjects(subjects: dict[int, tuple[str, int]])` — bulk-insert/update subjects into the cache.
- `has_cached_subjects() -> bool` — quick check if cache is populated.

### 2. Pin `Wanikani-Revision` header

In `app/routes.py` where the `httpx.AsyncClient` is created, add `"Wanikani-Revision": "20170710"` to the headers dict. This is a one-liner that protects against future breaking API changes.

### 3. Use `updated_after` for incremental sync

In `app/wanikani.py`:

- `fetch_kanji_level_map()` — accept an optional `updated_after` param; append `&updated_after=<ts>` to the URL when set.
- `fetch_passed_kanji()` — same pattern.
- `sync()` — read `sync_meta` for each endpoint before calling, pass the timestamp, then write back the current time after success.

On first sync (no `sync_meta` row), the full fetch happens as today. On subsequent syncs, only changed records are fetched.

### 4. Add conditional requests and local content caching

The WaniKani API returns `ETag` and `Last-Modified` headers on responses. Use conditional requests to validate cached data without re-downloading it, and store response content locally so we can serve from cache on 304.

#### Conditional request flow in `_request_with_retry()`

- When `sync_meta` has an `etag`, send `If-None-Match: <etag>`.
- When `sync_meta` has a `last_modified`, send `If-Modified-Since: <last_modified>` (ETag takes precedence per the API docs, but send both when available).
- On HTTP 304 (Not Modified): return a sentinel (e.g. `None`) to signal "use cached data".
- On HTTP 200: capture the `ETag` and `Last-Modified` response headers and return them alongside the data.

#### Content caching in `sync()`

- **Subjects (kanji level map):**
  - On 200: store the parsed `{subject_id: (character, level)}` map into `subject_cache` via `upsert_cached_subjects()`, then update `sync_meta` with the new ETag/Last-Modified/timestamp.
  - On 304: load the map from `subject_cache` via `get_cached_subjects()` — no network data to process.
  - On first sync (no cache): full fetch + populate cache as with 200.
- **Assignments (passed kanji):** These change more often (during level-ups), so `updated_after` (step 3) is the primary optimization. Still store/check ETags so a "nothing changed" sync is a single 304 response rather than a full paginated fetch.

This layered approach means: `updated_after` narrows the server-side query, conditional headers short-circuit the response when nothing changed, and the local cache provides the data without a round-trip to the API.

### 5. Add 429 retry with backoff in `_paginate()`

Wrap the request in `_paginate()` with retry logic:

- On HTTP 429, read `RateLimit-Reset` header, sleep until that timestamp (or fall back to exponential backoff starting at 1s).
- Cap at 3 retries per request.
- This is the only place we need it since all paginated and single-resource fetches flow through similar `client.get()` calls. Extract a small `_request_with_retry()` helper used by both `_paginate()` and `fetch_user()`.

### 6. Tests

- Test `_request_with_retry()` handles 429 with mocked sleep.
- Test `sync()` uses `updated_after` when `sync_meta` has a prior timestamp.
- Test `sync_meta` DB helpers (including ETag and Last-Modified storage/retrieval).
- Test `subject_cache` DB helpers: `upsert_cached_subjects()`, `get_cached_subjects()`, `has_cached_subjects()`.
- Test that `If-None-Match` and `If-Modified-Since` headers are sent when stored in `sync_meta`.
- Test that HTTP 304 for subjects causes `sync()` to load from `subject_cache` instead of parsing a response.
- Test that HTTP 304 for assignments skips processing and retains existing data.
- Test full sync round-trip: first sync populates cache, second sync hits 304 and uses cache.

## Verification

1. `uv run pytest` — all tests pass.
2. Manual: run sync twice and confirm the second sync uses `updated_after` params and conditional headers (visible in logs or by inspecting the httpx request).
3. Manual: confirm that a second sync with no WaniKani changes results in 304 responses and no re-processing.
