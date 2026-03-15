# DB Module: Replace Global Connection with Database Class

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the module-level `_conn` global in `app/db.py` with a `Database` class, making the connection an explicit instance attribute instead of hidden mutable state.

**Architecture:** Create a `Database` class that owns the SQLite connection and exposes all current module-level functions as methods. Wire it into FastAPI via dependency injection (`Depends`), so routes receive the instance explicitly. Tests construct `Database(":memory:")` directly.

**Tech Stack:** Python, SQLite, FastAPI (Depends), pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/db.py` | Modify | Wrap all functions in a `Database` class; connection becomes `self.conn` |
| `main.py` | Modify | Create `Database` instance in lifespan, store on `app.state` |
| `app/routes.py` | Modify | Define `get_db` dependency; accept `db: Database` via `Depends(get_db)` in each route |
| `tests/conftest.py` | Modify | Fixture creates `Database(":memory:")` and yields it |
| `tests/test_db.py` | Modify | Use `Database(":memory:")` instance directly; replace `db._conn` with `fresh_db.conn` |
| `tests/test_routes.py` | Modify | Use `app.dependency_overrides[get_db]` to inject test db |

## Chunk 1: Database class (Task 1)

### Task 1: Create the `Database` class in `app/db.py` and update db tests

**Files:**
- Modify: `app/db.py`
- Modify: `tests/conftest.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write a failing test that constructs `Database`**

Add a new test class at the top of `tests/test_db.py`:

```python
from app.db import Database


class TestDatabaseClass:
    def test_creates_tables_on_init(self):
        database = Database(":memory:")
        cursor = database.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor}
        assert tables == {
            "characters",
            "cards",
            "reviews",
            "sync_meta",
            "subject_cache",
        }
        database.close()
```

Run: `uv run pytest tests/test_db.py::TestDatabaseClass::test_creates_tables_on_init -v`
Expected: FAIL — `ImportError: cannot import name 'Database' from 'app.db'`

- [ ] **Step 2: Implement the `Database` class and remove old module-level functions**

Replace the entire contents of `app/db.py` with:

```python
import sqlite3
from datetime import datetime
from typing import Optional

from fsrs import Card, State

_SCHEMA = """
CREATE TABLE IF NOT EXISTS characters (
    kanji       TEXT NOT NULL PRIMARY KEY,
    wk_level    INT  NOT NULL CHECK (wk_level BETWEEN 1 AND 60),
    synced_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    kanji       TEXT NOT NULL PRIMARY KEY REFERENCES characters(kanji),
    state       INT  NOT NULL DEFAULT 1 CHECK (state IN (1, 2, 3)),
    step        INT,
    stability   REAL,
    difficulty  REAL,
    due         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now')),
    last_review TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER NOT NULL PRIMARY KEY,
    kanji       TEXT    NOT NULL REFERENCES characters(kanji),
    rating      INT     NOT NULL CHECK (rating IN (1, 2, 3, 4)),
    reviewed_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_meta (
    endpoint        TEXT NOT NULL PRIMARY KEY,
    synced_at       TEXT NOT NULL,
    etag            TEXT,
    last_modified   TEXT
);

CREATE TABLE IF NOT EXISTS subject_cache (
    id          INTEGER NOT NULL PRIMARY KEY,
    characters  TEXT NOT NULL,
    level       INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str = "stroke-memorize.db") -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def upsert_character(self, kanji: str, wk_level: int, synced_at: str) -> None:
        self.conn.execute(
            """
            INSERT INTO characters (kanji, wk_level, synced_at)
            VALUES (?, ?, ?)
            ON CONFLICT(kanji) DO UPDATE SET
                wk_level  = excluded.wk_level,
                synced_at = excluded.synced_at
            """,
            (kanji, wk_level, synced_at),
        )
        self.conn.commit()

    def insert_card_if_new(self, kanji: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO cards (kanji) VALUES (?)",
            (kanji,),
        )
        self.conn.commit()

    def get_review_kanji(self, now: str) -> list[str]:
        """Return kanji with due <= now that have been reviewed before."""
        rows = self.conn.execute(
            "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NOT NULL",
            (now,),
        ).fetchall()
        return [row["kanji"] for row in rows]

    def get_new_kanji(self, now: str) -> list[str]:
        """Return kanji with due <= now that have never been reviewed."""
        rows = self.conn.execute(
            "SELECT kanji FROM cards WHERE due <= ? AND last_review IS NULL ORDER BY RANDOM()",
            (now,),
        ).fetchall()
        return [row["kanji"] for row in rows]

    def count_review_due(self, now: str) -> int:
        """Count review cards due by the given time."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NOT NULL",
            (now,),
        ).fetchone()
        return row[0]

    def count_new_due(self, now: str) -> int:
        """Count new cards due by the given time."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM cards WHERE due <= ? AND last_review IS NULL",
            (now,),
        ).fetchone()
        return row[0]

    def count_new_introduced_today(self, today_start: str) -> int:
        """Count kanji whose first-ever review happened on or after today_start."""
        row = self.conn.execute(
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

    def get_card(self, kanji: str) -> Card:
        row = self.conn.execute(
            "SELECT * FROM cards WHERE kanji = ?",
            (kanji,),
        ).fetchone()
        if row is None:
            raise ValueError(f"No card found for kanji: {kanji!r}")
        return Card(
            state=State(row["state"]),
            step=row["step"],
            stability=row["stability"],
            difficulty=row["difficulty"],
            due=datetime.fromisoformat(row["due"]),
            last_review=(
                datetime.fromisoformat(row["last_review"]) if row["last_review"] else None
            ),
        )

    def update_card(self, kanji: str, card: Card) -> None:
        cursor = self.conn.execute(
            """
            UPDATE cards
            SET state = ?, step = ?, stability = ?, difficulty = ?, due = ?, last_review = ?
            WHERE kanji = ?
            """,
            (
                card.state.value,
                card.step,
                card.stability,
                card.difficulty,
                card.due.isoformat(),
                card.last_review.isoformat() if card.last_review else None,
                kanji,
            ),
        )
        if cursor.rowcount == 0:
            raise ValueError(f"No card found for kanji: {kanji!r}")
        self.conn.commit()

    def insert_review(self, kanji: str, rating: int, reviewed_at: str) -> None:
        self.conn.execute(
            "INSERT INTO reviews (kanji, rating, reviewed_at) VALUES (?, ?, ?)",
            (kanji, rating, reviewed_at),
        )
        self.conn.commit()

    def get_sync_meta(self, endpoint: str) -> dict | None:
        row = self.conn.execute(
            "SELECT synced_at, etag, last_modified FROM sync_meta WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        if row is None:
            return None
        return {
            "synced_at": row["synced_at"],
            "etag": row["etag"],
            "last_modified": row["last_modified"],
        }

    def set_sync_meta(
        self,
        endpoint: str,
        synced_at: str,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO sync_meta (endpoint, synced_at, etag, last_modified)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(endpoint) DO UPDATE SET
                synced_at     = excluded.synced_at,
                etag          = excluded.etag,
                last_modified = excluded.last_modified
            """,
            (endpoint, synced_at, etag, last_modified),
        )
        self.conn.commit()

    def get_cached_subjects(self) -> dict[int, tuple[str, int]]:
        rows = self.conn.execute("SELECT id, characters, level FROM subject_cache").fetchall()
        return {row["id"]: (row["characters"], row["level"]) for row in rows}

    def upsert_cached_subjects(self, subjects: dict[int, tuple[str, int]]) -> None:
        self.conn.executemany(
            """
            INSERT INTO subject_cache (id, characters, level)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                characters = excluded.characters,
                level      = excluded.level
            """,
            [(sid, chars, level) for sid, (chars, level) in subjects.items()],
        )
        self.conn.commit()
```

Run: `uv run pytest tests/test_db.py::TestDatabaseClass::test_creates_tables_on_init -v`
Expected: PASS

- [ ] **Step 3: Verify existing tests fail (they still use old module-level API)**

Run: `uv run pytest tests/test_db.py -v`
Expected: FAIL — existing tests still use `db.upsert_character(...)` and `db._conn` which no longer exist.

- [ ] **Step 4: Update `tests/conftest.py` to yield a `Database` instance**

Replace the entire contents of `tests/conftest.py` with:

```python
import pytest
from app.db import Database


@pytest.fixture(autouse=True)
def fresh_db():
    """Use an in-memory SQLite database for every test."""
    database = Database(":memory:")
    yield database
    database.close()
```

- [ ] **Step 5: Update `tests/test_db.py` to use the `fresh_db` fixture**

Replace the entire contents of `tests/test_db.py` with:

```python
import pytest
from datetime import datetime, timezone
from fsrs import Card, State
from app.db import Database


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestDatabaseClass:
    def test_creates_tables_on_init(self):
        database = Database(":memory:")
        cursor = database.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor}
        assert tables == {
            "characters",
            "cards",
            "reviews",
            "sync_meta",
            "subject_cache",
        }
        database.close()


class TestSchema:
    def test_tables_created(self, fresh_db):
        cursor = fresh_db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor}
        assert tables == {
            "characters",
            "cards",
            "reviews",
            "sync_meta",
            "subject_cache",
        }


class TestUpsertCharacter:
    def test_inserts_new_character(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        row = fresh_db.conn.execute(
            "SELECT kanji, wk_level FROM characters WHERE kanji = '一'"
        ).fetchone()
        assert tuple(row) == ("一", 1)

    def test_updates_existing_character(self, fresh_db):
        ts1 = "2024-01-01T00:00:00+00:00"
        ts2 = "2025-01-01T00:00:00+00:00"
        fresh_db.upsert_character("一", 1, ts1)
        fresh_db.upsert_character("一", 1, ts2)
        row = fresh_db.conn.execute(
            "SELECT synced_at FROM characters WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == ts2

    def test_rejects_invalid_level(self, fresh_db):
        with pytest.raises(Exception):
            fresh_db.upsert_character("一", 61, now_iso())


class TestInsertCardIfNew:
    def test_inserts_card_for_new_kanji(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        row = fresh_db.conn.execute(
            "SELECT state, stability, difficulty FROM cards WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == 1  # State.Learning
        assert row[1] is None  # stability NULL
        assert row[2] is None  # difficulty NULL

    def test_does_not_overwrite_existing_card(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        fresh_db.conn.execute("UPDATE cards SET stability = 9.5 WHERE kanji = '一'")
        fresh_db.conn.commit()
        fresh_db.insert_card_if_new("一")  # must not overwrite
        row = fresh_db.conn.execute(
            "SELECT stability FROM cards WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == 9.5


class TestGetReviewKanji:
    def test_returns_reviewed_due_kanji(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        fresh_db.conn.execute(
            "UPDATE cards SET last_review = ? WHERE kanji = '一'",
            (now_iso(),),
        )
        fresh_db.conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        assert "一" in fresh_db.get_review_kanji(now)

    def test_excludes_new_cards(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        now = datetime.now(timezone.utc).isoformat()
        assert fresh_db.get_review_kanji(now) == []


class TestGetNewKanji:
    def test_returns_new_due_kanji(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        now = datetime.now(timezone.utc).isoformat()
        assert "一" in fresh_db.get_new_kanji(now)

    def test_excludes_future_cards(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        fresh_db.conn.execute(
            "UPDATE cards SET due = '2099-01-01T00:00:00+00:00' WHERE kanji = '一'"
        )
        fresh_db.conn.commit()
        now = datetime.now(timezone.utc).isoformat()
        assert fresh_db.get_new_kanji(now) == []


class TestCountNewIntroducedToday:
    def test_counts_first_reviews_today(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_review("一", 3, now_iso())
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        assert fresh_db.count_new_introduced_today(today_start) == 1

    def test_ignores_old_reviews(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_review("一", 3, "2020-01-01T00:00:00+00:00")
        today_start = (
            datetime.now(timezone.utc)
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
        )
        assert fresh_db.count_new_introduced_today(today_start) == 0


class TestGetCard:
    def test_returns_fsrs_card(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        card = fresh_db.get_card("一")
        assert isinstance(card, Card)
        assert card.state == State.Learning
        assert card.stability is None
        assert card.difficulty is None
        assert card.last_review is None


class TestUpdateCard:
    def test_persists_updated_card(self, fresh_db):
        from fsrs import Scheduler, Rating

        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_card_if_new("一")
        card = fresh_db.get_card("一")
        scheduler = Scheduler()
        updated_card, _ = scheduler.review_card(card, Rating.Good)
        fresh_db.update_card("一", updated_card)
        reloaded = fresh_db.get_card("一")
        assert reloaded.stability == updated_card.stability
        assert reloaded.state == updated_card.state


class TestInsertReview:
    def test_inserts_review_row(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        fresh_db.insert_review("一", 3, now_iso())
        row = fresh_db.conn.execute(
            "SELECT kanji, rating FROM reviews WHERE kanji = '一'"
        ).fetchone()
        assert tuple(row) == ("一", 3)

    def test_rejects_invalid_rating(self, fresh_db):
        fresh_db.upsert_character("一", 1, now_iso())
        with pytest.raises(Exception):
            fresh_db.insert_review("一", 5, now_iso())


class TestSyncMeta:
    def test_get_sync_meta_returns_none_when_absent(self, fresh_db):
        assert fresh_db.get_sync_meta("subjects") is None

    def test_set_and_get_sync_meta(self, fresh_db):
        fresh_db.set_sync_meta(
            "subjects",
            "2024-01-01T00:00:00+00:00",
            etag='"abc"',
            last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
        )
        meta = fresh_db.get_sync_meta("subjects")
        assert meta is not None
        assert meta["synced_at"] == "2024-01-01T00:00:00+00:00"
        assert meta["etag"] == '"abc"'
        assert meta["last_modified"] == "Wed, 01 Jan 2025 00:00:00 GMT"

    def test_set_sync_meta_without_etag(self, fresh_db):
        fresh_db.set_sync_meta("assignments", "2024-06-01T00:00:00+00:00")
        meta = fresh_db.get_sync_meta("assignments")
        assert meta is not None
        assert meta["etag"] is None
        assert meta["last_modified"] is None

    def test_set_sync_meta_overwrites_existing(self, fresh_db):
        fresh_db.set_sync_meta("subjects", "2024-01-01T00:00:00+00:00", etag='"old"')
        fresh_db.set_sync_meta("subjects", "2025-01-01T00:00:00+00:00", etag='"new"')
        meta = fresh_db.get_sync_meta("subjects")
        assert meta["synced_at"] == "2025-01-01T00:00:00+00:00"
        assert meta["etag"] == '"new"'

    def test_different_endpoints_stored_independently(self, fresh_db):
        fresh_db.set_sync_meta("subjects", "2024-01-01T00:00:00+00:00", etag='"s1"')
        fresh_db.set_sync_meta("assignments", "2024-06-01T00:00:00+00:00", etag='"a1"')
        assert fresh_db.get_sync_meta("subjects")["etag"] == '"s1"'
        assert fresh_db.get_sync_meta("assignments")["etag"] == '"a1"'


class TestGetNewKanjiOrder:
    def test_new_kanji_not_always_in_insertion_order(self, fresh_db):
        """New kanji should be returned in random order, not insertion order."""
        now = datetime.now(timezone.utc).isoformat()
        kanji_list = [chr(0x4E00 + i) for i in range(20)]  # 20 kanji
        for k in kanji_list:
            fresh_db.upsert_character(k, 1, now)
            fresh_db.insert_card_if_new(k)

        # Run 5 times — if order is random, at least one should differ
        results = [tuple(fresh_db.get_new_kanji(now)) for _ in range(5)]
        assert len(set(results)) > 1, "get_new_kanji returned identical order every time"


class TestSubjectCache:
    def test_upsert_and_get_cached_subjects(self, fresh_db):
        subjects = {440: ("一", 1), 441: ("二", 1), 500: ("山", 3)}
        fresh_db.upsert_cached_subjects(subjects)
        result = fresh_db.get_cached_subjects()
        assert result == subjects

    def test_upsert_updates_existing_subjects(self, fresh_db):
        fresh_db.upsert_cached_subjects({440: ("一", 1)})
        fresh_db.upsert_cached_subjects({440: ("一", 2)})  # level changed
        result = fresh_db.get_cached_subjects()
        assert result[440] == ("一", 2)

    def test_upsert_merges_with_existing(self, fresh_db):
        fresh_db.upsert_cached_subjects({440: ("一", 1)})
        fresh_db.upsert_cached_subjects({441: ("二", 1)})
        result = fresh_db.get_cached_subjects()
        assert 440 in result and 441 in result
```

Run: `uv run pytest tests/test_db.py -v`
Expected: ALL PASS (all 24 tests)

- [ ] **Step 6: Commit**

```bash
git add app/db.py tests/test_db.py tests/conftest.py
git commit -m "refactor: replace db module-level global with Database class"
```

## Chunk 2: FastAPI DI wiring (Task 2)

### Task 2: Wire `Database` into FastAPI via dependency injection

**Files:**
- Modify: `main.py`
- Modify: `app/routes.py`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Update `main.py` to create `Database` in lifespan**

Replace the entire contents of `main.py` with:

```python
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.routes import router

load_dotenv()


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.db = Database(os.getenv("DB_PATH", "stroke-memorize.db"))
    yield
    application.state.db.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
```

- [ ] **Step 2: Update `app/routes.py` to use dependency injection**

Replace the entire contents of `app/routes.py` with:

```python
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.core import (
    compute_due_count,
    process_sync_results,
    requeue_position,
    schedule_review,
    select_due_cards,
)
from app.db import Database
from app.strokes import parse_strokes
from app.wanikani import fetch_subjects, fetch_passed_assignments, make_client

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

_sessions: dict[str, list[str]] = {}

_NEW_CARDS_PER_DAY: int = int(os.getenv("NEW_CARDS_PER_DAY", "20"))


def get_db(request: Request) -> Database:
    return request.app.state.db


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
async def home(request: Request, db: Database = Depends(get_db)):
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
async def do_sync(request: Request, db: Database = Depends(get_db)):
    api_key = os.getenv("WANIKANI_API_KEY")
    if not api_key:
        return HTMLResponse("<p>Error: WANIKANI_API_KEY not set in .env</p>")
    try:
        async with make_client(api_key) as client:
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
    request: Request,
    db: Database = Depends(get_db),
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
    return templates.TemplateResponse(request, "card.html", {"kanji": queue[0]})


@router.get("/session/strokes", response_class=HTMLResponse)
async def session_strokes(
    request: Request,
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        return HTMLResponse("<p>No active session.</p>")
    strokes = parse_strokes(queue[0])
    return templates.TemplateResponse(request, "strokes.html", {"strokes": strokes})


@router.post("/session/review", response_class=HTMLResponse)
async def session_review(
    request: Request,
    rating: Annotated[int, Form()],
    db: Database = Depends(get_db),
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

    # Requeue "Again" cards back into the session
    pos = requeue_position(rating, len(queue))
    if pos is not None:
        queue.insert(pos, kanji)

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

- [ ] **Step 3: Update `tests/test_routes.py` to use dependency overrides**

Replace the entire contents of `tests/test_routes.py` with:

```python
import re

import httpx
import pytest
import pytest_asyncio
import respx
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timezone

from app.db import Database
from app.routes import get_db


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest_asyncio.fixture
async def client(fresh_db, monkeypatch):
    # Prevent the lifespan from creating a real database file on disk.
    monkeypatch.setenv("DB_PATH", ":memory:")

    from main import app

    app.dependency_overrides[get_db] = lambda: fresh_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_home_returns_200(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "stroke" in resp.text.lower()


@pytest.mark.asyncio
async def test_sync_without_api_key_returns_error_partial(client):
    # No WANIKANI_API_KEY set in test environment
    resp = await client.post("/sync")
    assert resp.status_code == 200  # HTMX expects 200
    assert "WANIKANI_API_KEY" in resp.text or "error" in resp.text.lower()


@pytest.mark.asyncio
async def test_session_redirects_to_done_when_no_due_cards(client):
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/done")


@pytest.mark.asyncio
async def test_session_redirects_to_card_when_cards_due(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/card")


@pytest.mark.asyncio
async def test_session_card_displays_kanji(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert resp.status_code == 200
    assert "一" in resp.text


@pytest.mark.asyncio
async def test_session_strokes_returns_svg_paths(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/strokes")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "<path" in resp.text


@pytest.mark.asyncio
async def test_session_review_valid_rating_advances_queue(client, fresh_db):
    for kanji in ["一", "二"]:
        fresh_db.upsert_character(kanji, 1, now_iso())
        fresh_db.insert_card_if_new(kanji)
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    # FSRS review row inserted
    row = fresh_db.conn.execute("SELECT COUNT(*) FROM reviews").fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_session_review_last_card_triggers_hx_redirect(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    assert resp.headers.get("hx-redirect", "").endswith("/session/done")


@pytest.mark.asyncio
async def test_session_done_returns_200(client):
    resp = await client.get("/session/done")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_home_shows_new_count(client, fresh_db, monkeypatch):
    import app.routes as routes

    monkeypatch.setattr(routes, "_NEW_CARDS_PER_DAY", 1)
    for kanji in ["一", "二", "三"]:
        fresh_db.upsert_character(kanji, 1, now_iso())
        fresh_db.insert_card_if_new(kanji)
    resp = await client.get("/")
    assert "1 new" in resp.text


@pytest.mark.asyncio
async def test_session_review_again_requeues_card(client, fresh_db):
    """Rating 'Again' should re-insert the card into the session queue."""
    for kanji in ["一", "二", "三"]:
        fresh_db.upsert_character(kanji, 1, now_iso())
        fresh_db.insert_card_if_new(kanji)
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
async def test_sync_creates_characters_and_cards(client, fresh_db, monkeypatch):
    monkeypatch.setenv("WANIKANI_API_KEY", "test-key")
    respx.get(url__startswith=f"{BASE}/v2/subjects").mock(
        return_value=httpx.Response(200, json=_SUBJECTS_PAGE)
    )
    respx.get(url__startswith=f"{BASE}/v2/assignments").mock(
        return_value=httpx.Response(200, json=_ASSIGNMENTS_PAGE)
    )
    resp = await client.post("/sync")
    assert resp.status_code == 200
    assert "1 kanji" in resp.text
    # Verify DB side effects
    char_row = fresh_db.conn.execute(
        "SELECT wk_level FROM characters WHERE kanji = '一'"
    ).fetchone()
    assert char_row["wk_level"] == 1
    card_row = fresh_db.conn.execute("SELECT kanji FROM cards WHERE kanji = '一'").fetchone()
    assert card_row is not None
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add main.py app/routes.py tests/test_routes.py
git commit -m "refactor: wire Database into routes via FastAPI dependency injection"
```

## Chunk 3: Cleanup (Task 3)

### Task 3: Remove dead code and verify

- [ ] **Step 1: Verify no remaining references to old API**

Run these searches — each should return zero results:

```bash
uv run python -c "
import subprocess, sys
patterns = ['db\\.init\\(', 'db\\._conn', 'global _conn', 'import app\\.db as db']
found = False
for pat in patterns:
    result = subprocess.run(['grep', '-rn', pat, 'app/', 'tests/', 'main.py'], capture_output=True, text=True)
    if result.stdout.strip():
        print(f'FOUND {pat}:')
        print(result.stdout)
        found = True
if not found:
    print('No stale references found.')
"
```

Expected output: `No stale references found.`

If any stale references are found, remove them from the identified files.

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: ALL PASS

- [ ] **Step 3: Commit (only if changes were made in Step 1)**

```bash
git add -u
git commit -m "refactor: remove dead code from db module global cleanup"
```
