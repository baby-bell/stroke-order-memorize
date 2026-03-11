# stroke-memorize Backend & Frontend Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local FastAPI + HTMX web app for practising Japanese kanji stroke order, sourcing cards from WaniKani and scheduling reviews with FSRS.

**Architecture:** FastAPI serves Jinja2 templates. HTMX drives all navigation and partial swaps — no client-side routing. Session state (review queue) lives in a server-side dict keyed by a session cookie. SQLite via stdlib `sqlite3` stores characters, FSRS card state, and review history.

**Tech Stack:** Python 3.14, FastAPI, Jinja2, HTMX 2.x, SQLite, `fsrs` (Scheduler/Card/Rating/State), `kanjivg`, `httpx`, `python-dotenv`, `pytest`, `pytest-asyncio`, `respx`

**Key facts about dependencies:**
- `fsrs.State`: `Learning=1`, `Review=2`, `Relearning=3` — no `New` state; new cards start as `Learning`
- `fsrs.Scheduler().review_card(card, rating)` returns `tuple[Card, ReviewLog]`
- KanjiVG SVG files are at `<site-packages>/kanji/<5-hex-codepoint>.svg` (e.g. `04e00.svg` for 一)
- KanjiVG SVGs have two sibling `<g>` groups: `kvg:StrokePaths_*` (paths) and `kvg:StrokeNumbers_*` (text labels)

---

## Chunk 1: Foundation & Database

### Task 1: Dependencies and project scaffolding

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Install application dependencies**

```bash
uv add fastapi uvicorn jinja2 python-multipart httpx python-dotenv fsrs kanjivg
```

Expected: `pyproject.toml` updated with all 8 packages resolved successfully.

- [ ] **Step 2: Install dev dependencies**

```bash
uv add --dev pytest pytest-asyncio respx
```

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p app/templates app/static tests
touch app/__init__.py tests/__init__.py
```

- [ ] **Step 4: Add entries to .gitignore**

Open `.gitignore` and append:
```
stroke-memorize.db
.env
.superpowers/
```

- [ ] **Step 4b: Create .env.example**

```bash
echo "WANIKANI_API_KEY=your-api-key-here" > .env.example
```

- [ ] **Step 5: Create tests/conftest.py**

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

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .gitignore .env.example app/ tests/
git commit -m "feat: scaffold project structure and install dependencies"
```

---

### Task 2: Database layer

**Files:**
- Create: `app/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_db.py`:

```python
import pytest
from datetime import datetime, timezone
from fsrs import Card, State
import app.db as db


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TestSchema:
    def test_tables_created(self):
        cursor = db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor}
        assert tables == {"characters", "cards", "reviews"}


class TestUpsertCharacter:
    def test_inserts_new_character(self):
        db.upsert_character("一", 1, now_iso())
        row = db._conn.execute(
            "SELECT kanji, wk_level FROM characters WHERE kanji = '一'"
        ).fetchone()
        assert row == ("一", 1)

    def test_updates_existing_character(self):
        ts1 = "2024-01-01T00:00:00+00:00"
        ts2 = "2025-01-01T00:00:00+00:00"
        db.upsert_character("一", 1, ts1)
        db.upsert_character("一", 1, ts2)
        row = db._conn.execute(
            "SELECT synced_at FROM characters WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == ts2

    def test_rejects_invalid_level(self):
        with pytest.raises(Exception):
            db.upsert_character("一", 61, now_iso())


class TestInsertCardIfNew:
    def test_inserts_card_for_new_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        row = db._conn.execute(
            "SELECT state, stability, difficulty FROM cards WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == 1       # State.Learning
        assert row[1] is None    # stability NULL
        assert row[2] is None    # difficulty NULL

    def test_does_not_overwrite_existing_card(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        db._conn.execute("UPDATE cards SET stability = 9.5 WHERE kanji = '一'")
        db._conn.commit()
        db.insert_card_if_new("一")  # must not overwrite
        row = db._conn.execute(
            "SELECT stability FROM cards WHERE kanji = '一'"
        ).fetchone()
        assert row[0] == 9.5


class TestGetDueKanji:
    def test_returns_due_kanji(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        # New cards are due immediately (due DEFAULT = now)
        due = db.get_due_kanji()
        assert "一" in due

    def test_excludes_future_cards(self):
        db.upsert_character("二", 1, now_iso())
        db.insert_card_if_new("二")
        db._conn.execute(
            "UPDATE cards SET due = '2099-01-01T00:00:00+00:00' WHERE kanji = '二'"
        )
        db._conn.commit()
        due = db.get_due_kanji()
        assert "二" not in due


class TestGetCard:
    def test_returns_fsrs_card(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        card = db.get_card("一")
        assert isinstance(card, Card)
        assert card.state == State.Learning
        assert card.stability is None
        assert card.difficulty is None
        assert card.last_review is None


class TestUpdateCard:
    def test_persists_updated_card(self):
        from fsrs import Scheduler, Rating
        db.upsert_character("一", 1, now_iso())
        db.insert_card_if_new("一")
        card = db.get_card("一")
        scheduler = Scheduler()
        updated_card, _ = scheduler.review_card(card, Rating.Good)
        db.update_card("一", updated_card)
        reloaded = db.get_card("一")
        assert reloaded.stability == updated_card.stability
        assert reloaded.state == updated_card.state


class TestInsertReview:
    def test_inserts_review_row(self):
        db.upsert_character("一", 1, now_iso())
        db.insert_review("一", 3, now_iso())
        row = db._conn.execute(
            "SELECT kanji, rating FROM reviews WHERE kanji = '一'"
        ).fetchone()
        assert row == ("一", 3)

    def test_rejects_invalid_rating(self):
        db.upsert_character("一", 1, now_iso())
        with pytest.raises(Exception):
            db.insert_review("一", 5, now_iso())


class TestDueCount:
    def test_returns_count_of_due_cards(self):
        for kanji in ["一", "二"]:
            db.upsert_character(kanji, 1, now_iso())
            db.insert_card_if_new(kanji)
        assert db.due_count() == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_db.py -v
```

Expected: All fail with `ModuleNotFoundError` or `AttributeError`.

- [ ] **Step 3: Implement app/db.py**

```python
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from fsrs import Card, State

_conn: Optional[sqlite3.Connection] = None

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
    due         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    last_review TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER NOT NULL PRIMARY KEY,
    kanji       TEXT    NOT NULL REFERENCES characters(kanji),
    rating      INT     NOT NULL CHECK (rating IN (1, 2, 3, 4)),
    reviewed_at TEXT    NOT NULL
);
"""


def init(path: str = "stroke-memorize.db") -> None:
    global _conn
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA foreign_keys = ON")
    _conn.executescript(_SCHEMA)
    _conn.commit()


def upsert_character(kanji: str, wk_level: int, synced_at: str) -> None:
    _conn.execute(
        """
        INSERT INTO characters (kanji, wk_level, synced_at)
        VALUES (?, ?, ?)
        ON CONFLICT(kanji) DO UPDATE SET
            wk_level  = excluded.wk_level,
            synced_at = excluded.synced_at
        """,
        (kanji, wk_level, synced_at),
    )
    _conn.commit()


def insert_card_if_new(kanji: str) -> None:
    _conn.execute(
        "INSERT OR IGNORE INTO cards (kanji) VALUES (?)",
        (kanji,),
    )
    _conn.commit()


def get_due_kanji() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    rows = _conn.execute(
        "SELECT kanji FROM cards WHERE due <= ?",
        (now,),
    ).fetchall()
    return [row["kanji"] for row in rows]


def due_count() -> int:
    now = datetime.now(timezone.utc).isoformat()
    row = _conn.execute(
        "SELECT COUNT(*) FROM cards WHERE due <= ?",
        (now,),
    ).fetchone()
    return row[0]


def get_card(kanji: str) -> Card:
    row = _conn.execute(
        "SELECT * FROM cards WHERE kanji = ?",
        (kanji,),
    ).fetchone()
    return Card(
        state=State(row["state"]),
        step=row["step"],
        stability=row["stability"],
        difficulty=row["difficulty"],
        due=datetime.fromisoformat(row["due"]),
        last_review=(
            datetime.fromisoformat(row["last_review"])
            if row["last_review"]
            else None
        ),
    )


def update_card(kanji: str, card: Card) -> None:
    _conn.execute(
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
    _conn.commit()


def insert_review(kanji: str, rating: int, reviewed_at: str) -> None:
    _conn.execute(
        "INSERT INTO reviews (kanji, rating, reviewed_at) VALUES (?, ?, ?)",
        (kanji, rating, reviewed_at),
    )
    _conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_db.py -v
```

Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add app/db.py tests/test_db.py tests/conftest.py
git commit -m "feat: add database layer with SQLite and FSRS card persistence"
```

---

## Chunk 2: Data Clients

### Task 3: KanjiVG stroke parser

**Files:**
- Create: `app/strokes.py`
- Create: `tests/test_strokes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_strokes.py`:

```python
import pytest
from app.strokes import svg_path_for, parse_strokes


class TestSvgPathFor:
    def test_finds_svg_for_ichi(self):
        path = svg_path_for("一")
        assert path.exists()
        assert path.name == "04e00.svg"

    def test_finds_svg_for_hi(self):
        path = svg_path_for("日")
        assert path.exists()
        assert path.name == "065e5.svg"

    def test_raises_for_unknown_char(self):
        # Private-use area character not in KanjiVG
        with pytest.raises(FileNotFoundError):
            svg_path_for("\ue000")


class TestParseStrokes:
    def test_ichi_has_one_stroke(self):
        strokes = parse_strokes("一")
        assert len(strokes) == 1

    def test_stroke_tuple_has_four_elements(self):
        path_d, label, x, y = parse_strokes("一")[0]
        assert path_d.startswith("M")   # SVG path Move command
        assert label == "1"
        float(x)  # must be numeric
        float(y)

    def test_hi_has_four_strokes(self):
        strokes = parse_strokes("日")
        assert len(strokes) == 4

    def test_labels_are_sequential(self):
        strokes = parse_strokes("日")
        labels = [s[1] for s in strokes]
        assert labels == ["1", "2", "3", "4"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_strokes.py -v
```

Expected: All fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement app/strokes.py**

```python
import pathlib
import re
import site
import xml.etree.ElementTree as ET

_SVG_NS = "http://www.w3.org/2000/svg"
_E = f"{{{_SVG_NS}}}"


def svg_path_for(char: str) -> pathlib.Path:
    """Return the canonical (non-Kaisho) KanjiVG SVG path for a single character."""
    codepoint = format(ord(char), "05x")
    for sp in site.getsitepackages():
        p = pathlib.Path(sp) / "kanji" / f"{codepoint}.svg"
        # Skip variant files (e.g. 04e00-Kaisho.svg); canonical file has no hyphen
        if p.exists() and "-" not in p.stem:
            return p
    raise FileNotFoundError(f"No KanjiVG SVG for {char!r} (U+{codepoint.upper()})")


def _matrix_xy(transform: str) -> tuple[str, str]:
    """Extract x, y from 'matrix(1 0 0 1 x y)'."""
    nums = re.findall(r"[-\d.]+", transform)
    if len(nums) >= 6:
        return nums[4], nums[5]
    return "0", "0"


def parse_strokes(char: str) -> list[tuple[str, str, str, str]]:
    """
    Return stroke data for a character as a list of
    (path_d, label_text, label_x, label_y) tuples in stroke order.
    """
    svg_file = svg_path_for(char)
    codepoint = format(ord(char), "05x")
    tree = ET.parse(svg_file)
    root = tree.getroot()

    paths: list[str] = []
    for g in root.iter(f"{_E}g"):
        if g.get("id") == f"kvg:StrokePaths_{codepoint}":
            for path_el in g.iter(f"{_E}path"):
                paths.append(path_el.get("d", ""))
            break

    labels: list[tuple[str, str, str]] = []
    for g in root.iter(f"{_E}g"):
        if g.get("id") == f"kvg:StrokeNumbers_{codepoint}":
            for text_el in g.iter(f"{_E}text"):
                x, y = _matrix_xy(text_el.get("transform", ""))
                labels.append((text_el.text or "", x, y))
            break

    return [(d, lbl, x, y) for d, (lbl, x, y) in zip(paths, labels)]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_strokes.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add app/strokes.py tests/test_strokes.py
git commit -m "feat: add KanjiVG SVG parser for stroke data"
```

---

### Task 4: WaniKani API client

**Files:**
- Create: `app/wanikani.py`
- Create: `tests/test_wanikani.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_wanikani.py`:

```python
import pytest
import respx
import httpx
from datetime import datetime, timezone
import app.db as db
from app.wanikani import fetch_user, fetch_kanji_level_map, fetch_passed_kanji, sync

BASE = "https://api.wanikani.com"


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
async def test_sync_upserts_characters_and_creates_cards(wk_client):
    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
            },
        )
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"data": {"subject_id": 440}}],
            },
        )
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
    # Pre-populate a card with FSRS state
    db.upsert_character("一", 1, "2024-01-01T00:00:00+00:00")
    db.insert_card_if_new("一")
    db._conn.execute("UPDATE cards SET stability = 7.7 WHERE kanji = '一'")
    db._conn.commit()

    respx.get(f"{BASE}/v2/subjects?types=kanji").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"id": 440, "data": {"characters": "一", "level": 1}}],
            },
        )
    )
    respx.get(f"{BASE}/v2/assignments?subject_type=kanji&passed_at=true").mock(
        return_value=httpx.Response(
            200,
            json={
                "pages": {"next_url": None},
                "data": [{"data": {"subject_id": 440}}],
            },
        )
    )
    await sync(wk_client)
    row = db._conn.execute(
        "SELECT stability FROM cards WHERE kanji = '一'"
    ).fetchone()
    assert row["stability"] == 7.7  # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_wanikani.py -v
```

Expected: All fail with `ModuleNotFoundError`.

- [ ] **Step 3: Implement app/wanikani.py**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_wanikani.py -v
```

Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add app/wanikani.py tests/test_wanikani.py
git commit -m "feat: add WaniKani API v2 client with paginated sync"
```

---

## Chunk 3: Web Application

### Task 5: FastAPI app skeleton + home route

**Files:**
- Create: `main.py`
- Create: `app/routes.py` (stub)
- Create: `app/templates/base.html`
- Create: `app/templates/home.html`
- Create: `tests/test_routes.py` (home test only)

- [ ] **Step 1: Write failing test**

Create `tests/test_routes.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
import app.db as db
from datetime import datetime, timezone


def now_iso():
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
async def client():
    from main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.mark.asyncio
async def test_home_returns_200(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "stroke" in resp.text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_routes.py::test_home_returns_200 -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Create main.py**

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

- [ ] **Step 4: Create stub app/routes.py**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import app.db as db

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    count = db.due_count()
    return templates.TemplateResponse(
        "home.html", {"request": request, "due_count": count}
    )
```

- [ ] **Step 5: Create app/templates/base.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>stroke-memorize</title>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <script src="/static/strokes.js" defer></script>
  <style>
    body { font-family: sans-serif; max-width: 600px; margin: 2rem auto; padding: 0 1rem; }
    .kanji-display { font-size: 8rem; text-align: center; margin: 2rem 0; line-height: 1; }
    .rating-buttons { display: flex; gap: 1rem; justify-content: center; margin-top: 1.5rem; }
    .rating-buttons button { padding: 0.5rem 1.5rem; font-size: 1rem; cursor: pointer; }
    .rating-buttons button:disabled { opacity: 0.4; cursor: default; }
    button { padding: 0.5rem 1rem; font-size: 1rem; cursor: pointer; }
    svg { display: block; margin: 0 auto; }
  </style>
</head>
<body>
  <h1><a href="/" style="text-decoration:none;color:inherit">stroke-memorize</a></h1>
  {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 6: Create app/templates/home.html**

```html
{% extends "base.html" %}
{% block content %}
<p>{{ due_count }} card{{ "s" if due_count != 1 else "" }} due for review.</p>
<div id="sync-status"></div>
<form hx-post="/sync" hx-target="#sync-status" hx-swap="innerHTML">
  <button type="submit">Sync WaniKani</button>
</form>
{% if due_count > 0 %}
<p><a href="/session"><button>Start Session</button></a></p>
{% endif %}
{% endblock %}
```

- [ ] **Step 7: Create placeholder app/static/strokes.js** (full implementation in Task 8)

```javascript
// Stroke slideshow — implemented in Task 8
function initStrokes(total) {}
function nextStroke() {}
```

- [ ] **Step 8: Run test to verify it passes**

```bash
uv run pytest tests/test_routes.py::test_home_returns_200 -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add main.py app/routes.py app/templates/base.html app/templates/home.html app/static/strokes.js
git commit -m "feat: add FastAPI app skeleton with home route"
```

---

### Task 6: All remaining routes

**Files:**
- Modify: `app/routes.py`
- Create: `app/templates/_card_partial.html`
- Create: `app/templates/card.html`
- Create: `app/templates/strokes.html`
- Create: `app/templates/done.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Add failing tests for all remaining routes**

Append to `tests/test_routes.py`:

```python
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
async def test_session_redirects_to_card_when_cards_due(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/card")


@pytest.mark.asyncio
async def test_session_card_displays_kanji(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert resp.status_code == 200
    assert "一" in resp.text


@pytest.mark.asyncio
async def test_session_strokes_returns_svg_paths(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/strokes")
    assert resp.status_code == 200
    assert "<svg" in resp.text
    assert "<path" in resp.text


@pytest.mark.asyncio
async def test_session_review_valid_rating_advances_queue(client):
    for kanji in ["一", "二"]:
        db.upsert_character(kanji, 1, now_iso())
        db.insert_card_if_new(kanji)
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    # FSRS review row inserted
    row = db._conn.execute("SELECT COUNT(*) FROM reviews").fetchone()
    assert row[0] == 1


@pytest.mark.asyncio
async def test_session_review_last_card_triggers_hx_redirect(client):
    db.upsert_character("一", 1, now_iso())
    db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.post("/session/review", data={"rating": "3"})
    assert resp.status_code == 200
    assert resp.headers.get("hx-redirect", "").endswith("/session/done")


@pytest.mark.asyncio
async def test_session_done_returns_200(client):
    resp = await client.get("/session/done")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
uv run pytest tests/test_routes.py -v
```

Expected: New tests fail (routes not implemented yet).

- [ ] **Step 3: Create app/templates/_card_partial.html**

```html
<div class="kanji-display">{{ kanji }}</div>
<div id="stroke-area">
  <button hx-get="/session/strokes"
          hx-target="#stroke-area"
          hx-swap="innerHTML">Show Strokes</button>
</div>
<div class="rating-buttons">
  <button class="rating-btn" disabled
          hx-post="/session/review"
          hx-target="#card-body"
          hx-swap="innerHTML"
          hx-vals='{"rating": "1"}'>Again</button>
  <button class="rating-btn" disabled
          hx-post="/session/review"
          hx-target="#card-body"
          hx-swap="innerHTML"
          hx-vals='{"rating": "2"}'>Hard</button>
  <button class="rating-btn" disabled
          hx-post="/session/review"
          hx-target="#card-body"
          hx-swap="innerHTML"
          hx-vals='{"rating": "3"}'>Good</button>
  <button class="rating-btn" disabled
          hx-post="/session/review"
          hx-target="#card-body"
          hx-swap="innerHTML"
          hx-vals='{"rating": "4"}'>Easy</button>
</div>
```

- [ ] **Step 4: Create app/templates/card.html**

```html
{% extends "base.html" %}
{% block content %}
<div id="card-body">
  {% include "_card_partial.html" %}
</div>
{% endblock %}
```

- [ ] **Step 5: Create app/templates/strokes.html**

```html
<svg viewBox="0 0 109 109" width="300" height="300"
     style="fill:none;stroke:#000;stroke-width:3;stroke-linecap:round;stroke-linejoin:round;">
  {% for path_d, label, x, y in strokes %}
  <path class="stroke" data-stroke="{{ loop.index0 }}"
        d="{{ path_d }}"
        style="opacity:0"/>
  <text class="stroke-label" data-stroke="{{ loop.index0 }}"
        x="{{ x }}" y="{{ y }}"
        style="display:none;font-size:8px;fill:#808080">{{ label }}</text>
  {% endfor %}
</svg>
<p>Stroke <span id="stroke-count">0</span> of {{ strokes|length }}</p>
<button id="next-stroke-btn" onclick="nextStroke()">Next Stroke</button>
<script>initStrokes({{ strokes|length }});</script>
```

- [ ] **Step 6: Create app/templates/done.html**

```html
{% extends "base.html" %}
{% block content %}
<h2>Session complete!</h2>
<p>No more cards due right now.</p>
<p><a href="/"><button>Back to home</button></a></p>
{% endblock %}
```

- [ ] **Step 7: Implement remaining routes in app/routes.py**

Replace `app/routes.py` with:

```python
import os
import random
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fsrs import Rating, Scheduler

import app.db as db
from app.strokes import parse_strokes
from app.wanikani import sync

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

# Server-side session store: session_id -> ordered list of kanji to review
_sessions: dict[str, list[str]] = {}


def _queue(session_id: str | None) -> list[str]:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    return []


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    count = db.due_count()
    return templates.TemplateResponse(
        "home.html", {"request": request, "due_count": count}
    )


@router.post("/sync", response_class=HTMLResponse)
async def do_sync(request: Request):
    api_key = os.getenv("WANIKANI_API_KEY")
    if not api_key:
        return HTMLResponse("<p>Error: WANIKANI_API_KEY not set in .env</p>")
    try:
        async with httpx.AsyncClient(
            base_url="https://api.wanikani.com",
            headers={"Authorization": f"Bearer {api_key}"},
        ) as client:
            synced = await sync(client)
        return HTMLResponse(f"<p>Synced {len(synced)} kanji.</p>")
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(f"<p>Sync error: HTTP {exc.response.status_code}</p>")


@router.get("/session")
async def start_session(
    session_id: str | None = Cookie(default=None),
):
    due = db.get_due_kanji()
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
        "card.html", {"request": request, "kanji": queue[0]}
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
        "strokes.html", {"request": request, "strokes": strokes}
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
    card = db.get_card(kanji)
    updated_card, _ = Scheduler().review_card(card, Rating(rating))
    db.update_card(kanji, updated_card)
    db.insert_review(kanji, rating, datetime.now(timezone.utc).isoformat())

    if not queue:
        resp = HTMLResponse("")
        resp.headers["HX-Redirect"] = "/session/done"
        return resp

    return templates.TemplateResponse(
        "_card_partial.html", {"request": request, "kanji": queue[0]}
    )


@router.get("/session/done", response_class=HTMLResponse)
async def session_done(request: Request):
    return templates.TemplateResponse("done.html", {"request": request})
```

- [ ] **Step 8: Run all route tests**

```bash
uv run pytest tests/test_routes.py -v
```

Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add app/routes.py app/templates/
git commit -m "feat: add all routes and templates"
```

---

### Task 7: Stroke reveal JS (replace placeholder)

**Files:**
- Modify: `app/static/strokes.js`

- [ ] **Step 1: Replace placeholder with full implementation**

Overwrite `app/static/strokes.js`:

```javascript
let _strokeTotal = 0;
let _strokeIndex = 0;

function initStrokes(total) {
  _strokeTotal = total;
  _strokeIndex = 0;
  // Enable rating buttons now that strokes are loaded
  document.querySelectorAll('.rating-btn').forEach(btn => {
    btn.disabled = false;
  });
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = _strokeTotal === 0;
}

function nextStroke() {
  if (_strokeIndex >= _strokeTotal) return;
  document.querySelectorAll(`.stroke[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.opacity = '1';
  });
  document.querySelectorAll(`.stroke-label[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.display = '';
  });
  _strokeIndex++;
  const counter = document.getElementById('stroke-count');
  if (counter) counter.textContent = String(_strokeIndex);
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = _strokeIndex >= _strokeTotal;
}
```

- [ ] **Step 2: Manual smoke test**

```bash
echo "WANIKANI_API_KEY=your-actual-api-key" > .env
uv run uvicorn main:app --reload
```

Open http://localhost:8000 and verify:
1. Home page loads showing due count and Sync button
2. Sync button fetches WaniKani data and shows count in `#sync-status`
3. "Start Session" appears when cards are due
4. Card page shows the kanji character prominently
5. "Show Strokes" swaps in the SVG slideshow into `#stroke-area`; rating buttons are still disabled
6. Rating buttons become enabled as soon as the stroke slideshow loads (before any stroke is clicked)
7. "Next Stroke" reveals strokes one at a time; counter increments
8. Clicking Again/Hard/Good/Easy loads the next card (or triggers HX-Redirect to done)
9. Session Done page appears when queue is exhausted

- [ ] **Step 3: Commit**

```bash
git add app/static/strokes.js
git commit -m "feat: implement stroke reveal and rating enable JS"
```

---

### Task 8: Final checks and CLAUDE.md update

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest -v
```

Expected: All tests pass, no warnings about unraisable exceptions.

- [ ] **Step 2: Update CLAUDE.md**

`CLAUDE.md` already exists. Add a Commands section (append after the existing content):

```markdown
## Commands

- **Run:** `uv run uvicorn main:app --reload`
- **Test all:** `uv run pytest`
- **Single test:** `uv run pytest tests/test_db.py::TestUpsertCharacter -v`
- **Env:** copy `.env.example` to `.env` and fill in `WANIKANI_API_KEY`
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with run and test commands"
```
