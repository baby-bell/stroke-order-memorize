# Functional Core / Imperative Shell Refactor

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate pure business logic from I/O so the domain is testable without databases, HTTP, or filesystem.

**Architecture:** Extract a new `app/core.py` module containing all pure functions (daily-cap policy, sync result processing, review scheduling). `db.py` becomes thin CRUD. `routes.py` reads from DB, calls core, writes back. `wanikani.py` stays as HTTP-only; sync orchestration moves to `routes.py` calling core functions for decisions.

**Tech Stack:** Python 3.14, FastAPI, FSRS, SQLite, pytest

---

## File Structure

| File | Role | Changes |
|------|------|---------|
| `app/core.py` | **Functional core** — all pure business logic | **Create** |
| `tests/test_core.py` | Tests for pure functions | **Create** |
| `app/db.py` | **Imperative shell** — thin CRUD, no policy logic | **Modify**: remove daily-cap logic, remove `_new_cards_per_day` global |
| `tests/test_db.py` | DB tests | **Modify**: move policy tests to `test_core.py`, keep CRUD tests |
| `app/wanikani.py` | **Imperative shell** — HTTP fetching only | **Modify**: remove `sync()`, add `fetch_subjects`/`fetch_passed_assignments`, remove `import app.db` |
| `tests/test_wanikani.py` | WaniKani tests | **Modify**: remove `sync()` tests, add tests for new fetch functions |
| `app/routes.py` | **Imperative shell** — HTTP handlers wire I/O to core | **Modify**: use core functions, take over sync orchestration |
| `tests/test_routes.py` | Route integration tests | **Modify**: adjust for new wiring, add sync integration test |
| `main.py` | Entry point | **Modify**: remove `set_new_cards_per_day` call |
| `tests/conftest.py` | Test fixtures | **Modify**: remove `set_new_cards_per_day` call |

---

## Chunk 1: Extract pure core module

### Task 1: Create `app/core.py` with `select_due_cards`

This function implements the daily-cap policy currently embedded in `db.get_due_kanji()`.

**Files:**
- Create: `app/core.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core.py
from app.core import select_due_cards


class TestSelectDueCards:
    def test_returns_all_review_cards(self):
        result = select_due_cards(
            review_kanji=["一", "二"],
            new_kanji=["三"],
            new_today_count=0,
            daily_limit=20,
        )
        assert "一" in result
        assert "二" in result

    def test_includes_new_cards_up_to_limit(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二", "三"],
            new_today_count=0,
            daily_limit=2,
        )
        assert len(result) == 2

    def test_subtracts_already_introduced_today(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二", "三"],
            new_today_count=1,
            daily_limit=2,
        )
        assert len(result) == 1

    def test_zero_limit_excludes_all_new(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二"],
            new_today_count=0,
            daily_limit=0,
        )
        assert result == []

    def test_review_cards_always_included_even_with_zero_limit(self):
        result = select_due_cards(
            review_kanji=["一"],
            new_kanji=["二"],
            new_today_count=0,
            daily_limit=0,
        )
        assert result == ["一"]

    def test_limit_higher_than_available(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二"],
            new_today_count=0,
            daily_limit=100,
        )
        assert len(result) == 2

    def test_reviews_before_new_in_output(self):
        result = select_due_cards(
            review_kanji=["一"],
            new_kanji=["二", "三"],
            new_today_count=0,
            daily_limit=20,
        )
        assert result == ["一", "二", "三"]

    def test_today_count_exceeding_limit_clamps_to_zero(self):
        result = select_due_cards(
            review_kanji=[],
            new_kanji=["一", "二"],
            new_today_count=5,
            daily_limit=3,
        )
        assert result == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestSelectDueCards -v`
Expected: ImportError — `app.core` does not exist

- [ ] **Step 3: Write minimal implementation**

```python
# app/core.py
"""Functional core — pure business logic with no I/O."""


def select_due_cards(
    review_kanji: list[str],
    new_kanji: list[str],
    new_today_count: int,
    daily_limit: int,
) -> list[str]:
    """Select which cards to study: all review cards + new cards up to daily cap."""
    remaining_slots = max(0, daily_limit - new_today_count)
    return review_kanji + new_kanji[:remaining_slots]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestSelectDueCards -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/core.py tests/test_core.py
git commit -m "feat: add app/core.py with select_due_cards pure function"
```

---

### Task 2: Add `compute_due_count` to core

This is the pure equivalent of the logic in `db.due_count()`.

**Files:**
- Modify: `app/core.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_core.py
from app.core import compute_due_count


class TestComputeDueCount:
    def test_basic_counts(self):
        total, new = compute_due_count(
            review_count=3,
            new_available=5,
            new_today_count=0,
            daily_limit=20,
        )
        assert total == 8
        assert new == 5

    def test_caps_new_cards(self):
        total, new = compute_due_count(
            review_count=2,
            new_available=10,
            new_today_count=0,
            daily_limit=3,
        )
        assert total == 5
        assert new == 3

    def test_subtracts_already_introduced(self):
        total, new = compute_due_count(
            review_count=0,
            new_available=5,
            new_today_count=2,
            daily_limit=3,
        )
        assert total == 1
        assert new == 1

    def test_zero_limit(self):
        total, new = compute_due_count(
            review_count=1,
            new_available=5,
            new_today_count=0,
            daily_limit=0,
        )
        assert total == 1
        assert new == 0

    def test_today_count_exceeding_limit(self):
        total, new = compute_due_count(
            review_count=2,
            new_available=5,
            new_today_count=10,
            daily_limit=3,
        )
        assert total == 2
        assert new == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestComputeDueCount -v`
Expected: ImportError — `compute_due_count` not found

- [ ] **Step 3: Write minimal implementation**

```python
# append to app/core.py

def compute_due_count(
    review_count: int,
    new_available: int,
    new_today_count: int,
    daily_limit: int,
) -> tuple[int, int]:
    """Compute (total_due, new_due) given raw counts and daily cap."""
    remaining_slots = max(0, daily_limit - new_today_count)
    new_count = min(new_available, remaining_slots)
    return (review_count + new_count, new_count)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestComputeDueCount -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/core.py tests/test_core.py
git commit -m "feat: add compute_due_count to core"
```

---

### Task 3: Add `process_sync_results` to core

Extracts the pure logic from `wanikani.sync()` that filters passed assignment IDs against the level map.

**Files:**
- Modify: `app/core.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_core.py
from app.core import process_sync_results


class TestProcessSyncResults:
    def test_matches_passed_ids_to_level_map(self):
        level_map = {440: ("一", 1), 441: ("二", 1)}
        result = process_sync_results(
            passed_ids=[440, 441],
            level_map=level_map,
        )
        assert result == [("一", 1), ("二", 1)]

    def test_skips_unknown_subject_ids(self):
        level_map = {440: ("一", 1)}
        result = process_sync_results(
            passed_ids=[440, 999],
            level_map=level_map,
        )
        assert result == [("一", 1)]

    def test_empty_passed_ids(self):
        level_map = {440: ("一", 1)}
        result = process_sync_results(passed_ids=[], level_map=level_map)
        assert result == []

    def test_empty_level_map(self):
        result = process_sync_results(passed_ids=[440], level_map={})
        assert result == []

    def test_duplicate_passed_ids_produces_duplicates(self):
        level_map = {440: ("一", 1)}
        result = process_sync_results(passed_ids=[440, 440], level_map=level_map)
        assert result == [("一", 1), ("一", 1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestProcessSyncResults -v`
Expected: ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# append to app/core.py

def process_sync_results(
    passed_ids: list[int],
    level_map: dict[int, tuple[str, int]],
) -> list[tuple[str, int]]:
    """Filter passed assignment IDs against the subject level map.

    Returns [(kanji, level), ...] for IDs found in level_map.
    """
    return [
        level_map[sid]
        for sid in passed_ids
        if sid in level_map
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestProcessSyncResults -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/core.py tests/test_core.py
git commit -m "feat: add process_sync_results to core"
```

---

### Task 4: Add `schedule_review` to core

Wraps the FSRS scheduling call as a pure function. This makes the dependency on FSRS explicit and centralizes it in the core rather than having route handlers call FSRS directly.

**Files:**
- Modify: `app/core.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_core.py
from fsrs import Card, State
from app.core import schedule_review


class TestScheduleReview:
    def test_returns_updated_card(self):
        card = Card()  # default new card
        updated = schedule_review(card, rating=3)
        assert updated.last_review is not None
        assert updated.stability is not None

    def test_good_rating_sets_future_due(self):
        card = Card()
        updated = schedule_review(card, rating=3)
        assert updated.due > card.due

    def test_again_rating_keeps_learning(self):
        card = Card()
        updated = schedule_review(card, rating=1)
        assert updated.state == State.Learning

    def test_invalid_rating_raises(self):
        import pytest
        card = Card()
        with pytest.raises(ValueError):
            schedule_review(card, rating=0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestScheduleReview -v`
Expected: ImportError

- [ ] **Step 3: Write minimal implementation**

```python
# append to app/core.py
from fsrs import Card, Rating, Scheduler


def schedule_review(card: Card, rating: int) -> Card:
    """Apply an FSRS review and return the updated card.

    rating must be 1-4 (Again, Hard, Good, Easy). Raises ValueError otherwise.
    """
    updated_card, _ = Scheduler().review_card(card, Rating(rating))
    return updated_card
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestScheduleReview -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/core.py tests/test_core.py
git commit -m "feat: add schedule_review to core"
```

---

## Chunk 2: Refactor wanikani.py to HTTP-only

wanikani.py is refactored before routes.py so that `fetch_subjects` and `fetch_passed_assignments` exist when routes.py imports them.

### Task 5: Add `fetch_subjects` and `fetch_passed_assignments`, remove `sync()`

The `sync()` function is removed. Its HTTP-fetching logic is split into two functions that return data without touching the database. The sync orchestration will move to `routes.do_sync` in Chunk 3.

**Files:**
- Modify: `app/wanikani.py`
- Modify: `tests/test_wanikani.py`

- [ ] **Step 1: Add `fetch_subjects` and `fetch_passed_assignments` to `app/wanikani.py`**

Add these two functions. Remove `sync()` and `import app.db as db`.

Keep: `_request_with_retry`, `_paginate`, `_paginate_from_response`, `fetch_user`. Keep `fetch_kanji_level_map` and `fetch_passed_kanji` for now (removed in Task 9).

```python
async def fetch_subjects(
    client: httpx.AsyncClient,
    sync_meta: dict | None = None,
) -> tuple[dict[int, tuple[str, int]] | None, dict | None]:
    """Fetch kanji subjects from WaniKani, respecting conditional request headers.

    Returns (level_map, response_meta) where:
    - level_map is {subject_id: (kanji, level)} or None on 304
    - response_meta is {"etag": ..., "last_modified": ...} or None on 304
    """
    cond_headers: dict[str, str] = {}
    if sync_meta:
        if sync_meta["etag"]:
            cond_headers["If-None-Match"] = sync_meta["etag"]
        if sync_meta["last_modified"]:
            cond_headers["If-Modified-Since"] = sync_meta["last_modified"]

    url = f"{_WANIKANI_BASE}/v2/subjects?types=kanji"
    if sync_meta:
        url += f"&updated_after={sync_meta['synced_at']}"

    first_resp = await _request_with_retry(client, url, extra_headers=cond_headers)

    if first_resp is None:
        return None, None

    items = await _paginate_from_response(client, first_resp)
    level_map = {
        item["id"]: (item["data"]["characters"], item["data"]["level"])
        for item in items
    }
    response_meta = {
        "etag": first_resp.headers.get("etag"),
        "last_modified": first_resp.headers.get("last-modified"),
    }
    return level_map, response_meta


async def fetch_passed_assignments(
    client: httpx.AsyncClient,
    sync_meta: dict | None = None,
) -> tuple[list[int] | None, dict | None]:
    """Fetch passed kanji assignments from WaniKani.

    Returns (passed_ids, response_meta) where:
    - passed_ids is [subject_id, ...] or None on 304
    - response_meta is {"etag": ..., "last_modified": ...} or None on 304
    """
    cond_headers: dict[str, str] = {}
    if sync_meta:
        if sync_meta["etag"]:
            cond_headers["If-None-Match"] = sync_meta["etag"]
        if sync_meta["last_modified"]:
            cond_headers["If-Modified-Since"] = sync_meta["last_modified"]

    url = f"{_WANIKANI_BASE}/v2/assignments?subject_type=kanji&passed_at=true"
    if sync_meta:
        url += f"&updated_after={sync_meta['synced_at']}"

    first_resp = await _request_with_retry(client, url, extra_headers=cond_headers)

    if first_resp is None:
        return None, None

    items = await _paginate_from_response(client, first_resp)
    passed_ids = [item["data"]["subject_id"] for item in items]
    response_meta = {
        "etag": first_resp.headers.get("etag"),
        "last_modified": first_resp.headers.get("last-modified"),
    }
    return passed_ids, response_meta
```

- [ ] **Step 2: Update `tests/test_wanikani.py`**

Remove all `test_sync_*` tests. Add tests for the new functions. Update imports to include `fetch_subjects` and `fetch_passed_assignments`:

```python
# Add to imports:
from app.wanikani import fetch_subjects, fetch_passed_assignments

# Add these tests:

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
```

Remove the `import app.db as db` from the test file's imports if it was only used by sync tests.

- [ ] **Step 3: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS (routes still use the old `sync()` import — but we just removed it. We need to verify routes tests still pass since `do_sync` is the only caller.)

**Important:** At this point `app/routes.py` still imports `from app.wanikani import sync`. Since `sync()` was removed, the routes module will fail to import. To keep the suite green, also update the import in `app/routes.py` temporarily:

Replace `from app.wanikani import sync` with a placeholder that will be fully rewritten in Task 7:
```python
# In app/routes.py, temporarily change:
# from app.wanikani import sync
# to:
from app.wanikani import fetch_subjects, fetch_passed_assignments
```

And temporarily replace the body of `do_sync` to keep it functional (the full rewrite happens in Task 7):
```python
@router.post("/sync", response_class=HTMLResponse)
async def do_sync(request: Request):
    api_key = os.getenv("WANIKANI_API_KEY")
    if not api_key:
        return HTMLResponse("<p>Error: WANIKANI_API_KEY not set in .env</p>")
    try:
        async with httpx.AsyncClient(
            base_url="https://api.wanikani.com",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Wanikani-Revision": "20170710",
            },
        ) as client:
            now = datetime.now(timezone.utc).isoformat()

            subjects_meta = db.get_sync_meta("subjects")
            level_map, new_subjects_meta = await fetch_subjects(client, subjects_meta)
            if level_map is None:
                level_map = db.get_cached_subjects()
            else:
                db.upsert_cached_subjects(level_map)
                level_map = db.get_cached_subjects()  # re-read full merged cache
                if new_subjects_meta:
                    db.set_sync_meta("subjects", now, **new_subjects_meta)

            assignments_meta = db.get_sync_meta("assignments")
            passed_ids, new_assignments_meta = await fetch_passed_assignments(
                client, assignments_meta
            )
            if passed_ids is None:
                return HTMLResponse("<p>Synced 0 kanji.</p>")
            if new_assignments_meta:
                db.set_sync_meta("assignments", now, **new_assignments_meta)

            synced: list[tuple[str, int]] = []
            for subject_id in passed_ids:
                if subject_id not in level_map:
                    continue
                kanji, level = level_map[subject_id]
                db.upsert_character(kanji, level, now)
                db.insert_card_if_new(kanji)
                synced.append((kanji, level))

        return HTMLResponse(f"<p>Synced {len(synced)} kanji.</p>")
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(f"<p>Sync error: HTTP {exc.response.status_code}</p>")
```

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add app/wanikani.py app/routes.py tests/test_wanikani.py
git commit -m "refactor: wanikani.py is HTTP-only, remove sync() and db dependency"
```

---

## Chunk 3: Refactor db.py and routes.py together

These must be done together to keep the test suite green — removing db functions and updating their callers in the same commit.

### Task 6: Refactor `db.py` to thin CRUD

Remove the daily-cap policy from `db.py`. Replace composite functions with raw query functions.

**Files:**
- Modify: `app/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Replace composite functions with raw queries in `app/db.py`**

Remove: `_new_cards_per_day` global, `set_new_cards_per_day()`, `_new_introduced_today()`, `get_due_kanji()`, `due_count()`.

Add these raw query functions:

```python
def get_review_kanji(now: str) -> list[str]:
    """Return kanji with due <= now that have been reviewed before."""
    rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NOT NULL",
        (now,),
    ).fetchall()
    return [row["kanji"] for row in rows]


def get_new_kanji(now: str) -> list[str]:
    """Return kanji with due <= now that have never been reviewed."""
    rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL",
        (now,),
    ).fetchall()
    return [row["kanji"] for row in rows]


def count_review_due(now: str) -> int:
    """Count review cards due by the given time."""
    row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NOT NULL",
        (now,),
    ).fetchone()
    return row[0]


def count_new_due(now: str) -> int:
    """Count new cards due by the given time."""
    row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NULL",
        (now,),
    ).fetchone()
    return row[0]


def count_new_introduced_today(today_start: str) -> int:
    """Count kanji whose first-ever review happened on or after today_start."""
    row = _conn.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT kanji FROM reviews
            GROUP BY kanji
            HAVING MIN(reviewed_at) >= ?
        )
        """,
        (today_start,),
    ).fetchone()
    return row[0]
```

- [ ] **Step 2: Update `tests/test_db.py`**

Remove: `TestGetDueKanji`, `TestDueCount`, `TestNewCardLimit`, `TestDueCountWithLimit` classes.

Add tests for the new raw query functions:

```python
class TestGetReviewKanji:
    def test_returns_reviewed_due_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        assert "一" in db.get_review_kanji(now)

    def test_excludes_new_cards(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        now = datetime.now(timezone.utc).isoformat()
        assert db.get_review_kanji(now) == []


class TestGetNewKanji:
    def test_returns_new_due_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        now = datetime.now(timezone.utc).isoformat()
        assert "一" in db.get_new_kanji(now)

    def test_excludes_future_cards(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute(
            "UPDATE cards SET due = '2099-01-01T00:00:00+00:00' WHERE kanji = '一'"
        )
        db._conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        assert db.get_new_kanji(now) == []


class TestCountNewIntroducedToday:
    def test_counts_first_reviews_today(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_review("一", 3, now_iso())
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        assert db.count_new_introduced_today(today_start) == 1

    def test_ignores_old_reviews(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_review("一", 3, "2020-01-01T00:00:00+00:00")
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        assert db.count_new_introduced_today(today_start) == 0
```

- [ ] **Step 3: Run db tests**

Run: `uv run pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 4: Commit (do NOT commit yet — continue to Task 7)**

Do not commit yet. Task 7 must be done in the same commit to keep the suite green.

---

### Task 7: Refactor route handlers to use core functions

Routes become thin: read from DB → call core → write to DB → render.

**Files:**
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py`
- Modify: `tests/conftest.py`
- Modify: `main.py`

- [ ] **Step 1: Rewrite `routes.py`**

```python
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import app.db as db
from app.core import (
    compute_due_count,
    process_sync_results,
    schedule_review,
    select_due_cards,
)
from app.strokes import parse_strokes
from app.wanikani import fetch_subjects, fetch_passed_assignments

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

_sessions: dict[str, list[str]] = {}

_NEW_CARDS_PER_DAY: int = int(os.getenv("NEW_CARDS_PER_DAY", "20"))


def _today_start_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )


def _queue(session_id: str | None) -> list[str]:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    return []


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    now = datetime.now(timezone.utc).isoformat()
    total, new = compute_due_count(
        review_count=db.count_review_due(now),
        new_available=db.count_new_due(now),
        new_today_count=db.count_new_introduced_today(_today_start_iso()),
        daily_limit=_NEW_CARDS_PER_DAY,
    )
    return templates.TemplateResponse(
        request, "home.html", {"due_count": total, "new_count": new}
    )


@router.post("/sync", response_class=HTMLResponse)
async def do_sync(request: Request):
    api_key = os.getenv("WANIKANI_API_KEY")
    if not api_key:
        return HTMLResponse("<p>Error: WANIKANI_API_KEY not set in .env</p>")
    try:
        async with httpx.AsyncClient(
            base_url="https://api.wanikani.com",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Wanikani-Revision": "20170710",
            },
        ) as client:
            now = datetime.now(timezone.utc).isoformat()

            # Fetch subjects (with conditional request support)
            subjects_meta = db.get_sync_meta("subjects")
            level_map, new_subjects_meta = await fetch_subjects(client, subjects_meta)

            if level_map is None:
                # 304 — use cached
                level_map = db.get_cached_subjects()
            else:
                db.upsert_cached_subjects(level_map)
                level_map = db.get_cached_subjects()  # re-read full merged cache
                if new_subjects_meta:
                    db.set_sync_meta("subjects", now, **new_subjects_meta)

            # Fetch assignments (with conditional request support)
            assignments_meta = db.get_sync_meta("assignments")
            passed_ids, new_assignments_meta = await fetch_passed_assignments(
                client, assignments_meta
            )

            if passed_ids is None:
                # 304 — nothing new
                return HTMLResponse("<p>Synced 0 kanji.</p>")

            if new_assignments_meta:
                db.set_sync_meta("assignments", now, **new_assignments_meta)

            # Pure core: decide what to persist
            synced = process_sync_results(passed_ids, level_map)

            # Persist
            for kanji, level in synced:
                db.upsert_character(kanji, level, now)
                db.insert_card_if_new(kanji)

        return HTMLResponse(f"<p>Synced {len(synced)} kanji.</p>")
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(f"<p>Sync error: HTTP {exc.response.status_code}</p>")


@router.get("/session")
async def start_session(
    session_id: str | None = Cookie(default=None),
):
    now = datetime.now(timezone.utc).isoformat()
    due = select_due_cards(
        review_kanji=db.get_review_kanji(now),
        new_kanji=db.get_new_kanji(now),
        new_today_count=db.count_new_introduced_today(_today_start_iso()),
        daily_limit=_NEW_CARDS_PER_DAY,
    )
    if not due:
        return RedirectResponse("/session/done", status_code=303)
    random.shuffle(due)
    sid = session_id or str(uuid.uuid4())
    _sessions[sid] = due
    resp = RedirectResponse("/session/card", status_code=303)
    resp.set_cookie("session_id", sid)
    return resp


@router.get("/session/card", response_class=HTMLResponse)
async def session_card(
    request: Request,
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        return RedirectResponse("/session/done", status_code=303)
    return templates.TemplateResponse(
        request, "card.html", {"kanji": queue[0]}
    )


@router.get("/session/strokes", response_class=HTMLResponse)
async def session_strokes(
    request: Request,
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        return HTMLResponse("<p>No active session.</p>")
    strokes = parse_strokes(queue[0])
    return templates.TemplateResponse(
        request, "strokes.html", {"strokes": strokes}
    )


@router.post("/session/review", response_class=HTMLResponse)
async def session_review(
    request: Request,
    rating: Annotated[int, Form()],
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        resp = HTMLResponse("")
        resp.headers["HX-Redirect"] = "/session/done"
        return resp

    kanji = queue.pop(0)

    # Core: pure scheduling
    card = db.get_card(kanji)
    updated_card = schedule_review(card, rating)

    # Shell: persist
    db.update_card(kanji, updated_card)
    db.insert_review(kanji, rating, datetime.now(timezone.utc).isoformat())

    if not queue:
        resp = HTMLResponse("")
        resp.headers["HX-Redirect"] = "/session/done"
        return resp

    return templates.TemplateResponse(
        request, "_card_partial.html", {"kanji": queue[0]}
    )


@router.get("/session/done", response_class=HTMLResponse)
async def session_done(request: Request):
    return templates.TemplateResponse(request, "done.html", {})
```

- [ ] **Step 2: Update `tests/test_routes.py`**

Replace `test_home_shows_new_count` to use `monkeypatch` instead of the removed `db.set_new_cards_per_day`:

```python
@pytest.mark.asyncio
async def test_home_shows_new_count(client, monkeypatch):
    import app.routes as routes
    monkeypatch.setattr(routes, "_NEW_CARDS_PER_DAY", 1)
    for kanji in ["一", "二", "三"]:
        db.upsert_character(kanji, 1, now_iso())
        db.insert_card_if_new(kanji)
    resp = await client.get("/")
    assert "1 new" in resp.text
```

- [ ] **Step 3: Update `tests/conftest.py`**

Remove `db.set_new_cards_per_day(20)`:

```python
import pytest
import app.db as db


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    db.init(":memory:")
    yield
    if db._conn:
        db._conn.close()
        db._conn = None
```

- [ ] **Step 4: Update `main.py`**

Remove the `set_new_cards_per_day` call:

```python
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.db as db
from app.routes import router

load_dotenv()


@asynccontextmanager
async def lifespan(application: FastAPI):
    db.init(os.getenv("DB_PATH", "stroke-memorize.db"))
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add app/db.py app/routes.py tests/test_db.py tests/test_routes.py tests/conftest.py main.py
git commit -m "refactor: db.py thin CRUD, routes use core functions for all business logic"
```

---

## Chunk 4: Integration test and cleanup

### Task 8: Add sync integration test to `test_routes.py`

Verify the full `POST /sync` orchestration works end-to-end (HTTP mock → DB persistence).

**Files:**
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write the sync integration test**

```python
# append to tests/test_routes.py
import respx

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
async def test_sync_creates_characters_and_cards(client, monkeypatch):
    monkeypatch.setenv("WANIKANI_API_KEY", "test-key")
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
    )
    resp = await client.post("/sync")
    assert resp.status_code == 200
    assert "1 kanji" in resp.text
    # Verify DB side effects
    char_row = db._conn.execute(
        "SELECT wk_level FROM characters WHERE kanji = '一'"
    ).fetchone()
    assert char_row["wk_level"] == 1
    card_row = db._conn.execute(
        "SELECT kanji FROM cards WHERE kanji = '一'"
    ).fetchone()
    assert card_row is not None
```

Add `import httpx` to the top of `tests/test_routes.py` if not already present.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_routes.py::test_sync_creates_characters_and_cards -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_routes.py
git commit -m "test: add sync integration test for routes.do_sync orchestration"
```

---

### Task 9: Remove dead code and run full test suite

**Files:**
- Modify: `app/wanikani.py` — remove `fetch_kanji_level_map` and `fetch_passed_kanji` (superseded by `fetch_subjects`/`fetch_passed_assignments`)
- Modify: `tests/test_wanikani.py` — remove their tests
- Verify: `app/db.py` — confirm no dead functions remain

- [ ] **Step 1: Check for unused imports and functions**

Search for any remaining references to removed/superseded functions:
```bash
grep -rn "get_due_kanji\|due_count\|set_new_cards_per_day\|from app.wanikani import sync\|fetch_kanji_level_map\|fetch_passed_kanji\|_new_introduced_today\|has_cached_subjects" app/ tests/
```

- [ ] **Step 2: Remove dead code**

From `app/wanikani.py`, remove:
- `fetch_kanji_level_map` (superseded by `fetch_subjects`)
- `fetch_passed_kanji` (superseded by `fetch_passed_assignments`)

From `tests/test_wanikani.py`, remove:
- `test_fetch_kanji_level_map_single_page`
- `test_fetch_kanji_level_map_follows_pagination`
- `test_fetch_kanji_level_map_appends_updated_after`
- `test_fetch_passed_kanji`
- `test_fetch_passed_kanji_appends_updated_after`

Keep `fetch_user` (intentionally retained for future use) and `has_cached_subjects` (used by `do_sync` via `db.get_cached_subjects` path — verify it is still called; if not, remove).

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add app/wanikani.py tests/test_wanikani.py
git commit -m "chore: remove dead code after FC/IS refactor"
```

---

## Summary of what changes

**Before:** Business logic scattered across `db.py`, `routes.py`, and `wanikani.py`, interleaved with I/O.

**After:**

```
app/core.py          ← Pure functions: select_due_cards, compute_due_count,
                       process_sync_results, schedule_review
                       (testable with zero I/O)

app/db.py            ← Thin CRUD: get_review_kanji, get_new_kanji,
                       count_review_due, count_new_due, count_new_introduced_today,
                       get_card, update_card, insert_review, ...

app/wanikani.py      ← HTTP only: fetch_subjects, fetch_passed_assignments,
                       _request_with_retry, _paginate
                       (no db import)

app/routes.py        ← Imperative shell: reads DB → calls core → writes DB → renders
                       (orchestrates sync, sessions, reviews)
```
