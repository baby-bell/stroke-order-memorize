# Bugfix Quartet Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix four bugs: missing `lang="ja"` on kanji display, sync 422 errors from unencoded URL parameters, non-random new card selection, and "Again"-rated cards not reappearing in session.

**Architecture:** Bugs 2-4 follow functional core / imperative shell — pure logic in `app/core.py` tested in `tests/test_core.py`, with DB and route layers as thin shells. Bug 1 is a template-only fix.

**Tech Stack:** Python 3.14, FastAPI, HTMX, SQLite, FSRS, httpx, pytest

---

## Chunk 1: Bugs 1-4

### Task 1: Add `lang="ja"` to kanji display

**Files:**
- Modify: `app/templates/_card_partial.html:1`

- [ ] **Step 1: Add lang attribute**

In `app/templates/_card_partial.html`, change line 1 from:
```html
<div class="kanji-display">{{ kanji }}</div>
```
to:
```html
<div class="kanji-display" lang="ja">{{ kanji }}</div>
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/test_routes.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add app/templates/_card_partial.html
git commit -m "fix: add lang=ja to kanji display for correct glyph rendering"
```

---

### Task 2: Fix sync 422 from unencoded `updated_after` URL parameter

The `+` in ISO timestamps like `2024-01-01T00:00:00+00:00` is not URL-encoded when string-concatenated into the URL, causing WaniKani to reject the request with 422 on subsequent syncs.

**Files:**
- Modify: `app/wanikani.py:119-121` and `app/wanikani.py:157-159`
- Modify: `tests/test_wanikani.py`

- [ ] **Step 1: Write failing test for URL encoding**

Add to `tests/test_wanikani.py`:

```python
@respx.mock
@pytest.mark.asyncio
async def test_fetch_subjects_url_encodes_updated_after(wk_client):
    """updated_after with '+' in timezone must be properly URL-encoded."""
    prior = {"synced_at": "2024-01-01T00:00:00+00:00", "etag": None, "last_modified": None}
    route = respx.get(url__startswith=f"{BASE}/v2/subjects").mock(
        return_value=httpx.Response(200, json={"pages": {"next_url": None}, "data": []})
    )
    await fetch_subjects(wk_client, sync_meta=prior)
    request_url = str(route.calls[0].request.url)
    # The '+' must be encoded as %2B in the query string
    assert "%2B" in request_url or "+" not in request_url.split("updated_after=")[1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wanikani.py::test_fetch_subjects_url_encodes_updated_after -v`
Expected: FAIL — the `+` is not encoded

- [ ] **Step 3: Fix `fetch_subjects` to use httpx `params`**

In `app/wanikani.py`, change `fetch_subjects` URL construction (lines 119-121) from:

```python
    url = f"{_WANIKANI_BASE}/v2/subjects?types=kanji"
    if sync_meta:
        url += f"&updated_after={sync_meta['synced_at']}"
```

to:

```python
    params = {"types": "kanji"}
    if sync_meta:
        params["updated_after"] = sync_meta["synced_at"]
    url = f"{_WANIKANI_BASE}/v2/subjects"
```

Add a `params` keyword argument to `_request_with_retry` so callers can pass query parameters for proper URL encoding by httpx.

In `app/wanikani.py`, update `_request_with_retry`:
```python
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
```

Update `fetch_subjects` (lines 119-128):
```python
    url = f"{_WANIKANI_BASE}/v2/subjects"
    params = {"types": "kanji"}
    if sync_meta:
        params["updated_after"] = sync_meta["synced_at"]

    first_resp = await _request_with_retry(client, url, extra_headers=cond_headers, params=params)
```

Update `fetch_passed_assignments` (lines 157-161):
```python
    url = f"{_WANIKANI_BASE}/v2/assignments"
    params = {"subject_type": "kanji", "passed_at": "true"}
    if sync_meta:
        params["updated_after"] = sync_meta["synced_at"]

    first_resp = await _request_with_retry(client, url, extra_headers=cond_headers, params=params)
```

- [ ] **Step 4: Update existing tests for new URL matching**

After switching to httpx `params`, query parameters are properly encoded and may appear in different order. Update all `respx.get(...)` URL matchers in `tests/test_wanikani.py` and `tests/test_routes.py` to use `url__startswith` so they're resilient to parameter ordering and encoding.

**Pattern for tests without `sync_meta`** (no `updated_after` param):

```python
# Before:
respx.get(f"{BASE}/v2/subjects?types=kanji").mock(...)
# After:
respx.get(url__startswith=f"{BASE}/v2/subjects").mock(...)
```

**Pattern for tests with `sync_meta`** (has `updated_after` param):

```python
# Before:
respx.get(f"{BASE}/v2/subjects?types=kanji&updated_after={prior['synced_at']}").mock(...)
# After:
respx.get(url__startswith=f"{BASE}/v2/subjects").mock(...)
```

**Tests to update in `tests/test_wanikani.py`:**
- `test_fetch_subjects_returns_level_map` — change to `url__startswith=f"{BASE}/v2/subjects"`
- `test_fetch_subjects_returns_none_on_304` — same pattern
- `test_fetch_subjects_sends_conditional_headers` — same pattern
- `test_fetch_subjects_appends_updated_after` — same pattern; also update assertion to check the encoded URL contains `updated_after` and the timestamp value
- `test_fetch_passed_assignments_returns_ids` — change to `url__startswith=f"{BASE}/v2/assignments"`
- `test_fetch_passed_assignments_returns_none_on_304` — same pattern
- `test_fetch_passed_assignments_sends_conditional_headers` — same pattern

**Test to update in `tests/test_routes.py`:**
- `test_sync_creates_characters_and_cards` — change both `respx.get(...)` calls:

```python
respx.get(url__startswith=f"{BASE}/v2/subjects").mock(
    return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
)
respx.get(url__startswith=f"{BASE}/v2/assignments").mock(
    return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
)
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/test_wanikani.py tests/test_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/wanikani.py tests/test_wanikani.py tests/test_routes.py
git commit -m "fix: URL-encode updated_after param to prevent sync 422 errors"
```

---

### Task 3: Randomize new card selection

The `get_new_kanji()` SQL query has no `ORDER BY`, so new cards are returned in insertion order (WaniKani level order). Since `select_due_cards` takes only the first N via `new_kanji[:remaining_slots]`, lower-level cards are always preferred.

**Files:**
- Modify: `app/db.py:88-94`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_db.py`:

```python
class TestGetNewKanjiOrder:
    def test_new_kanji_not_always_in_insertion_order(self):
        """New kanji should be returned in random order, not insertion order."""
        now = datetime.now(timezone.utc).isoformat()
        kanji_list = [chr(0x4E00 + i) for i in range(20)]  # 20 kanji
        for k in kanji_list:
            db.upsert_character(k, 1, now)
            db.insert_card_if_new(k)

        # Run 5 times — if order is random, at least one should differ
        results = [tuple(db.get_new_kanji(now)) for _ in range(5)]
        assert len(set(results)) > 1, "get_new_kanji returned identical order every time"
```

`datetime` and `timezone` are already imported in `tests/test_db.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::TestGetNewKanjiOrder -v`
Expected: FAIL — identical order every time

- [ ] **Step 3: Add ORDER BY RANDOM()**

In `app/db.py`, change `get_new_kanji` (lines 88-94) from:
```python
    rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL",
        (now,),
    ).fetchall()
```
to:
```python
    rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL ORDER BY RANDOM()",
        (now,),
    ).fetchall()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_db.py tests/test_core.py tests/test_routes.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "fix: randomize new card selection instead of insertion order"
```

---

### Task 4: Re-queue "Again"-rated cards in session

When a user rates a card "Again" (rating=1), the card is popped from the queue and never seen again in the session. It should be re-inserted into the queue so the user gets another attempt.

**Files:**
- Create: (none — logic goes in existing `app/core.py`)
- Modify: `app/core.py`
- Modify: `app/routes.py:154-183`
- Modify: `tests/test_core.py`
- Modify: `tests/test_routes.py`

#### Step group A: Pure core function

- [ ] **Step 1: Write failing test for requeue logic**

Add to `tests/test_core.py`:

```python
from app.core import requeue_position


class TestRequeuePosition:
    def test_returns_none_for_good_rating(self):
        assert requeue_position(rating=3, queue_length=5) is None

    def test_returns_none_for_easy_rating(self):
        assert requeue_position(rating=4, queue_length=5) is None

    def test_returns_none_for_hard_rating(self):
        assert requeue_position(rating=2, queue_length=5) is None

    def test_returns_position_for_again_rating(self):
        pos = requeue_position(rating=1, queue_length=5)
        assert pos is not None
        assert 0 <= pos <= 5

    def test_position_within_bounds_small_queue(self):
        pos = requeue_position(rating=1, queue_length=1)
        assert pos is not None
        assert pos >= 0

    def test_position_zero_queue(self):
        """When queue is empty after pop, card goes at position 0 (back in)."""
        pos = requeue_position(rating=1, queue_length=0)
        assert pos == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_core.py::TestRequeuePosition -v`
Expected: FAIL — `requeue_position` does not exist

- [ ] **Step 3: Implement requeue_position**

Add to `app/core.py`:

```python
def requeue_position(rating: int, queue_length: int) -> int | None:
    """Return the index to re-insert a card at, or None if no requeue needed.

    Only "Again" (rating=1) triggers a requeue. The card is placed
    a few positions ahead so it's not immediate but comes back soon.
    """
    if rating != 1:
        return None
    if queue_length <= 1:
        return 0
    # Place 2-4 cards from front, capped at queue length
    offset = min(random.randint(2, 4), queue_length)
    return offset
```

Add `import random` to the top of `app/core.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_core.py::TestRequeuePosition -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/core.py tests/test_core.py
git commit -m "feat: add requeue_position pure function for Again-rated cards"
```

#### Step group B: Wire into route

- [ ] **Step 6: Write failing route test**

Add to `tests/test_routes.py`:

Add `import re` to the top of `tests/test_routes.py` with the other imports.

```python
@pytest.mark.asyncio
async def test_session_review_again_requeues_card(client):
    """Rating 'Again' should re-insert the card into the session queue."""
    for kanji in ["一", "二", "三"]:
        db.upsert_character(kanji, 1, now_iso())
        db.insert_card_if_new(kanji)
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
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/test_routes.py::test_session_review_again_requeues_card -v`
Expected: FAIL — only 2 cards seen after the first

- [ ] **Step 8: Wire requeue into session_review route**

In `app/routes.py`, update the import (line 13-18):
```python
from app.core import (
    compute_due_count,
    process_sync_results,
    requeue_position,
    schedule_review,
    select_due_cards,
)
```

Then update `session_review` (lines 166-174). After `kanji = queue.pop(0)`, add requeue logic:

```python
    kanji = queue.pop(0)

    # Core: pure scheduling
    card = db.get_card(kanji)
    updated_card = schedule_review(card, rating)

    # Shell: persist
    db.update_card(kanji, updated_card)
    db.insert_review(kanji, rating, datetime.now(timezone.utc).isoformat())

    # Requeue "Again" cards back into the session
    pos = requeue_position(rating, len(queue))
    if pos is not None:
        queue.insert(pos, kanji)
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 10: Commit**

```bash
git add app/routes.py app/core.py tests/test_routes.py
git commit -m "fix: requeue Again-rated cards so they reappear in session"
```
