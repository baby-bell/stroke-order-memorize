# Daily New Card Limit Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Limit how many never-reviewed ("new") cards appear in each day's review queue so the user isn't overwhelmed after a large WaniKani sync.

**Architecture:** Add a `_new_cards_per_day` config to `app/db.py`. Modify `get_due_kanji()` to split its query into review cards (always returned) and new cards (capped by daily limit minus already-introduced-today). Modify `due_count()` to return `(total, new)` tuple. Wire config from env var in `main.py`. Update route and template to display new count.

**Tech Stack:** Python 3.14, SQLite, FastAPI, Jinja2, pytest

**Key facts about existing code:**
- `app/db.py` has module-level `_conn` for the SQLite connection, set by `init()`
- `get_due_kanji()` returns `list[str]` — all kanji where `due <= now`
- `due_count()` returns `int` — count of all due cards
- `cards` table: `last_review` is NULL for never-reviewed cards
- `reviews` table: `reviewed_at TEXT NOT NULL`, one row per review event
- `tests/conftest.py` has `fresh_db()` autouse fixture calling `db.init(":memory:")`
- Home route passes `due_count` to `home.html`; template shows `{{ due_count }} cards due for review.`
- Existing `TestDueCount` test asserts `db.due_count() == 2` — this will break when return type changes to tuple

---

## Chunk 1: Daily New Card Limit

### Task 1: Add daily new card limit across db, routes, and UI

Since `due_count()` changes its return type from `int` to `tuple[int, int]`, the db layer, route, and template must all change together to avoid a broken intermediate state.

**Files:**
- Modify: `app/db.py`
- Modify: `app/routes.py`
- Modify: `app/templates/home.html`
- Modify: `main.py`
- Modify: `.env.example`
- Modify: `tests/test_db.py`
- Modify: `tests/test_routes.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write failing db tests**

Append to `tests/test_db.py`:

```python
class TestNewCardLimit:
    def test_new_cards_limited_to_daily_max(self):
        db.set_new_cards_per_day(2)
        for kanji in ["一", "二", "三", "四", "五"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        due = db.get_due_kanji()
        assert len(due) == 2

    def test_review_cards_always_included(self):
        db.set_new_cards_per_day(0)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        # Simulate a reviewed card: set last_review so it's not "new"
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        due = db.get_due_kanji()
        assert "一" in due

    def test_zero_limit_excludes_all_new_cards(self):
        db.set_new_cards_per_day(0)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        due = db.get_due_kanji()
        assert due == []

    def test_introduced_today_counts_toward_limit(self):
        db.set_new_cards_per_day(2)
        for kanji in ["一", "二", "三"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        # Simulate reviewing "一" today (its first-ever review)
        # In production update_card sets last_review; here we set it directly for isolation
        db.insert_review("一", 3, now_iso())
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        # "一" was introduced today, so only 1 new slot remains
        due = db.get_due_kanji()
        new_in_due = [k for k in due if k != "一"]
        assert len(new_in_due) == 1

    def test_limit_higher_than_available_new_cards(self):
        db.set_new_cards_per_day(100)
        for kanji in ["一", "二"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        due = db.get_due_kanji()
        assert len(due) == 2


class TestDueCountWithLimit:
    def test_returns_tuple_of_total_and_new(self):
        db.set_new_cards_per_day(20)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        result = db.due_count()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_counts_respect_new_card_limit(self):
        db.set_new_cards_per_day(1)
        for kanji in ["一", "二", "三"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        total, new = db.due_count()
        assert total == 1
        assert new == 1

    def test_counts_include_review_cards(self):
        db.set_new_cards_per_day(0)
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        db._conn.commit()
        total, new = db.due_count()
        assert total == 1
        assert new == 0
```

- [ ] **Step 2: Update existing TestDueCount test**

The existing `TestDueCount.test_returns_count_of_due_cards` asserts `db.due_count() == 2` which will break when the return type changes to tuple. Update it:

In `tests/test_db.py`, change:

```python
class TestDueCount:
    def test_returns_count_of_due_cards(self):
        for kanji in ["一", "二"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        assert db.due_count() == 2
```

To:

```python
class TestDueCount:
    def test_returns_count_of_due_cards(self):
        for kanji in ["一", "二"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        total, new = db.due_count()
        assert total == 2
        assert new == 2
```

- [ ] **Step 3: Write failing route test**

Append to `tests/test_routes.py`:

```python
@pytest.mark.asyncio
async def test_home_shows_new_count(client):
    db.set_new_cards_per_day(1)
    for kanji in ["一", "二", "三"]:
        db.upsert_character(kanji, 1, now_iso())
        db.insert_card_if_new(kanji)
    resp = await client.get("/")
    assert "1 new" in resp.text
```

- [ ] **Step 4: Update conftest.py to set default limit**

In `tests/conftest.py`, add a line after `db.init(":memory:")` so tests have a known default:

```python
import pytest
import app.db as db


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    db.init(":memory:")
    db.set_new_cards_per_day(20)
    yield
    if db._conn:
        db._conn.close()
        db._conn = None
```

- [ ] **Step 5: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py::TestNewCardLimit tests/test_db.py::TestDueCountWithLimit tests/test_routes.py::test_home_shows_new_count -v
```

Expected: All fail with `AttributeError: module 'app.db' has no attribute 'set_new_cards_per_day'`.

- [ ] **Step 6: Implement in app/db.py**

Add after the `_conn` declaration:

```python
_new_cards_per_day: int = 20


def set_new_cards_per_day(n: int) -> None:
    global _new_cards_per_day
    if not isinstance(n, int) or n < 0:
        raise ValueError(f"NEW_CARDS_PER_DAY must be a non-negative integer, got {n!r}")
    _new_cards_per_day = n
```

Add a new helper function (place before `get_due_kanji`):

```python
def _new_introduced_today() -> int:
    """Count kanji whose first-ever review happened today (UTC)."""
    today_start = (
        datetime.now(timezone.utc)
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
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

Replace `get_due_kanji()`:

```python
def get_due_kanji() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    # Review cards: always included
    review_rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NOT NULL",
        (now,),
    ).fetchall()
    review_kanji = [row["kanji"] for row in review_rows]

    # New cards: limited by daily cap
    remaining_slots = max(0, _new_cards_per_day - _new_introduced_today())
    new_rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL LIMIT ?",
        (now, remaining_slots),
    ).fetchall()
    new_kanji = [row["kanji"] for row in new_rows]

    return review_kanji + new_kanji
```

Replace `due_count()`:

```python
def due_count() -> tuple[int, int]:
    now = datetime.now(timezone.utc).isoformat()
    review_row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NOT NULL",
        (now,),
    ).fetchone()
    review_count = review_row[0]

    remaining_slots = max(0, _new_cards_per_day - _new_introduced_today())
    new_row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NULL",
        (now,),
    ).fetchone()
    new_count = min(new_row[0], remaining_slots)

    return (review_count + new_count, new_count)
```

- [ ] **Step 7: Update main.py**

Add config reading in the lifespan, after `db.init()`:

```python
@asynccontextmanager
async def lifespan(application: FastAPI):
    db.init(os.getenv("DB_PATH", "stroke-memorize.db"))
    new_cards = os.getenv("NEW_CARDS_PER_DAY", "20")
    db.set_new_cards_per_day(int(new_cards))
    yield
```

- [ ] **Step 8: Update app/routes.py home route**

Change the `home` function from:

```python
@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    count = db.due_count()
    return templates.TemplateResponse(
        request, "home.html", {"due_count": count}
    )
```

To:

```python
@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    total, new = db.due_count()
    return templates.TemplateResponse(
        request, "home.html", {"due_count": total, "new_count": new}
    )
```

- [ ] **Step 9: Update app/templates/home.html**

Change:

```html
<p>{{ due_count }} card{{ "s" if due_count != 1 else "" }} due for review.</p>
```

To:

```html
<p>{{ due_count }} card{{ "s" if due_count != 1 else "" }} due for review{% if new_count %} ({{ new_count }} new){% endif %}.</p>
```

- [ ] **Step 10: Update .env.example**

Append `NEW_CARDS_PER_DAY=20` to `.env.example`.

- [ ] **Step 11: Run all tests**

```bash
uv run pytest -v
```

Expected: All tests pass (existing + new).

- [ ] **Step 12: Commit**

```bash
git add app/db.py app/routes.py app/templates/home.html main.py .env.example tests/test_db.py tests/test_routes.py tests/conftest.py
git commit -m "feat: add daily new card limit with configurable NEW_CARDS_PER_DAY"
```
