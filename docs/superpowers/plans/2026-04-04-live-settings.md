# Live-Reloadable Settings Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store user-configurable settings in SQLite so they can be changed from a `/settings` page without restarting the server.

**Architecture:** Add a `settings` table to the existing SQLite schema. `Database` gets generic `get_setting`/`set_setting` methods. Routes read settings from DB per-request. A new `/settings` page provides the UI. The `_NEW_CARDS_PER_DAY` env-var constant is removed.

**Tech Stack:** FastAPI, SQLite, Jinja2, HTMX, pytest

**Spec:** `docs/superpowers/specs/2026-04-04-live-settings-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/db.py` | Modify | Add `settings` table to schema, add `get_setting`/`set_setting` methods |
| `app/routes.py` | Modify | Remove `_NEW_CARDS_PER_DAY` constant, add `_DEFAULT_NEW_CARDS_PER_DAY`, add `GET/POST /settings` routes, update 3 call sites |
| `app/templates/settings.html` | Create | Settings form page |
| `app/templates/home.html` | Modify | Add link to `/settings` |
| `.env.example` | Modify | Remove `NEW_CARDS_PER_DAY` line |
| `tests/test_db.py` | Modify | Add `TestSettings` class, update `TestDatabaseClass` table assertion |
| `tests/test_routes.py` | Modify | Migrate `test_home_shows_new_count`, add settings route tests |

---

## Chunk 1: Database Layer

### Task 1: Add `get_setting` / `set_setting` to Database

**Files:**
- Modify: `app/db.py:8-44` (schema), `app/db.py:47` (Database class)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for `get_setting` and `set_setting`**

Add to `tests/test_db.py`:

```python
class TestSettings:
    def test_get_setting_returns_default_when_unset(self, fresh_db):
        assert fresh_db.get_setting("new_cards_per_day", "20") == "20"

    def test_get_setting_returns_stored_value(self, fresh_db):
        fresh_db.set_setting("new_cards_per_day", "10")
        assert fresh_db.get_setting("new_cards_per_day", "20") == "10"

    def test_set_setting_upserts(self, fresh_db):
        fresh_db.set_setting("new_cards_per_day", "10")
        fresh_db.set_setting("new_cards_per_day", "5")
        assert fresh_db.get_setting("new_cards_per_day", "20") == "5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py::TestSettings -v`
Expected: FAIL with `AttributeError: 'Database' object has no attribute 'get_setting'`

- [ ] **Step 3: Add settings table to schema and implement methods**

In `app/db.py`, append to the `_SCHEMA` string (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);
```

Add methods to the `Database` class:

```python
def get_setting(self, key: str, default: str) -> str:
    row = self.conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row else default

def set_setting(self, key: str, value: str) -> None:
    with self.conn:
        self.conn.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
```

- [ ] **Step 4: Update table assertions (two places)**

In `tests/test_db.py`, both `TestDatabaseClass.test_creates_tables_on_init` (line 18) and `TestSchema.test_tables_created` (line 34) have identical expected table sets. Add `"settings"` to **both**:

```python
assert tables == {
    "characters",
    "cards",
    "reviews",
    "sync_meta",
    "subject_cache",
    "settings",
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app/db.py tests/test_db.py
git commit -m "feat: add generic settings table with get/set methods"
```

---

## Chunk 2: Routes and Templates

### Task 2: Wire settings into existing routes

**Files:**
- Modify: `app/routes.py:1,28,54,130,202`

- [ ] **Step 1: Write failing test for DB-backed setting**

In `tests/test_routes.py`, **replace** the existing `test_home_shows_new_count` (lines 117-125) entirely — remove the `monkeypatch` parameter and `setattr` call:

```python
@pytest.mark.asyncio
async def test_home_shows_new_count(client, fresh_db):
    fresh_db.set_setting("new_cards_per_day", "1")
    for kanji in ["一", "二", "三"]:
        fresh_db.upsert_character(kanji, 1, now_utc())
        fresh_db.insert_card_if_new(kanji)
    resp = await client.get("/")
    assert "1 new" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_routes.py::test_home_shows_new_count -v`
Expected: FAIL (still reading from env var constant, not DB)

- [ ] **Step 3: Replace constant with DB reads**

In `app/routes.py`:

Remove line 28:
```python
_NEW_CARDS_PER_DAY: int = int(os.getenv("NEW_CARDS_PER_DAY", "20"))
```

Add in its place:
```python
_DEFAULT_NEW_CARDS_PER_DAY = "20"
```

Note: keep the `os` import — it's still used for `os.getenv("WANIKANI_API_KEY")` on line 63.

Replace `daily_limit=_NEW_CARDS_PER_DAY` in three locations (home, start_session, session_review) with:
```python
daily_limit=int(db.get_setting("new_cards_per_day", _DEFAULT_NEW_CARDS_PER_DAY))
```

Note: `start_session` and `session_review` already have `db` via `Depends(get_db)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes.py tests/test_routes.py
git commit -m "feat: read new_cards_per_day from DB settings instead of env var"
```

### Task 3: Add settings page routes and template

**Files:**
- Modify: `app/routes.py`
- Create: `app/templates/settings.html`
- Modify: `app/templates/home.html`
- Test: `tests/test_routes.py`

- [ ] **Step 1: Write failing tests for settings routes**

Add to `tests/test_routes.py`:

```python
@pytest.mark.asyncio
async def test_settings_get_returns_200(client):
    resp = await client.get("/settings")
    assert resp.status_code == 200
    assert "20" in resp.text  # default value


@pytest.mark.asyncio
async def test_settings_post_updates_value(client, fresh_db):
    resp = await client.post(
        "/settings",
        data={"new_cards_per_day": "5"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/settings")
    assert fresh_db.get_setting("new_cards_per_day", "20") == "5"


@pytest.mark.asyncio
async def test_settings_post_rejects_negative(client, fresh_db):
    resp = await client.post(
        "/settings",
        data={"new_cards_per_day": "-1"},
    )
    assert resp.status_code == 200  # re-renders form
    assert "error" in resp.text.lower()
    # Value should not have changed
    assert fresh_db.get_setting("new_cards_per_day", "20") == "20"


@pytest.mark.asyncio
async def test_settings_post_rejects_non_numeric(client, fresh_db):
    resp = await client.post(
        "/settings",
        data={"new_cards_per_day": "abc"},
    )
    assert resp.status_code == 200
    assert "error" in resp.text.lower()
    assert fresh_db.get_setting("new_cards_per_day", "20") == "20"


@pytest.mark.asyncio
async def test_session_respects_db_setting(client, fresh_db):
    """start_session uses the DB-stored new_cards_per_day setting."""
    fresh_db.set_setting("new_cards_per_day", "0")
    for kanji in ["一", "二"]:
        fresh_db.upsert_character(kanji, 1, now_utc())
        fresh_db.insert_card_if_new(kanji)
    # With 0 new cards allowed and no review cards, session should redirect to done
    resp = await client.get("/session", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].endswith("/session/done")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_routes.py::test_settings_get_returns_200 tests/test_routes.py::test_settings_post_updates_value tests/test_routes.py::test_settings_post_rejects_negative tests/test_routes.py::test_settings_post_rejects_non_numeric -v`
Expected: FAIL with 404

- [ ] **Step 3: Create settings template**

Create `app/templates/settings.html`:

```html
{% extends "base.html" %}
{% block content %}
<h2>Settings</h2>
{% if error %}
<p style="color: red;">Error: {{ error }}</p>
{% endif %}
<form method="post" action="/settings">
  <label for="new_cards_per_day">New cards per day</label>
  <input type="number" id="new_cards_per_day" name="new_cards_per_day"
         value="{{ new_cards_per_day }}" min="0">
  <button type="submit">Save</button>
</form>
<p><a href="/">Home</a></p>
{% endblock %}
```

- [ ] **Step 4: Add settings routes**

In `app/routes.py`, add at the end:

```python
@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Database = Depends(get_db)):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "new_cards_per_day": db.get_setting(
                "new_cards_per_day", _DEFAULT_NEW_CARDS_PER_DAY
            ),
        },
    )


@router.post("/settings", response_class=HTMLResponse)
async def settings_update(
    request: Request,
    new_cards_per_day: Annotated[str, Form()],
    db: Database = Depends(get_db),
):
    try:
        value = int(new_cards_per_day)
        if value < 0:
            raise ValueError
    except (ValueError, TypeError):
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "new_cards_per_day": db.get_setting(
                    "new_cards_per_day", _DEFAULT_NEW_CARDS_PER_DAY
                ),
                "error": "New cards per day must be a non-negative integer.",
            },
        )
    db.set_setting("new_cards_per_day", str(value))
    return RedirectResponse("/settings", status_code=303)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Add settings link to home page**

In `app/templates/home.html`, add a link to `/settings` next to the existing `/stats` link. Change line 12:

```html
<p><a href="/stats">Statistics</a> · <a href="/settings">Settings</a></p>
```

- [ ] **Step 7: Commit**

```bash
git add app/routes.py app/templates/settings.html app/templates/home.html
git commit -m "feat: add /settings page for live-configurable new cards per day"
```

---

## Chunk 3: Cleanup

### Task 4: Remove env var from .env.example

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Remove `NEW_CARDS_PER_DAY` from `.env.example`**

`.env.example` should become:
```
WANIKANI_API_KEY=your-api-key-here
```

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "chore: remove NEW_CARDS_PER_DAY from .env.example, now in DB settings"
```
