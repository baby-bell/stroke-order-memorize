# Live-Reloadable Settings via SQLite

## Problem

`NEW_CARDS_PER_DAY` is read from an environment variable at import time and cannot be changed without restarting the server. The user wants to change it on the fly from the UI.

## Approach

Store settings in a generic SQLite `settings` table (key/value text pairs). Provide a `/settings` page to view and update them. Routes read from the DB on each request, so changes take effect immediately.

## Database Layer

### Schema addition

Append to the `_SCHEMA` string in `db.py`:

```sql
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);
```

### New methods on `Database`

```python
def get_setting(self, key: str, default: str) -> str:
    """Return the value for key, or default if not set."""

def set_setting(self, key: str, value: str) -> None:
    """Upsert a setting."""
```

Values are always stored as text. Callers handle type conversion (e.g., `int(db.get_setting("new_cards_per_day", "20"))`).

## Routes

### Removals

- Delete `_NEW_CARDS_PER_DAY` module-level constant and its `os.getenv` call. (The `os` import stays — it's still used for `WANIKANI_API_KEY`.)

### Modified call sites

Add a module-level default constant:

```python
_DEFAULT_NEW_CARDS_PER_DAY = "20"
```

Replace `daily_limit=_NEW_CARDS_PER_DAY` in `home`, `start_session`, and `session_review` with:

```python
daily_limit=int(db.get_setting("new_cards_per_day", _DEFAULT_NEW_CARDS_PER_DAY))
```

The same constant is used as the pre-fill value in `GET /settings` when no value has been stored yet.

### New routes

- `GET /settings` — renders `settings.html` with current values from DB (using `get_setting` with defaults).
- `POST /settings` — accepts form data, validates each value server-side (e.g., `new_cards_per_day` must be a non-negative integer), calls `db.set_setting(...)` for valid fields, redirects to `/settings`. Invalid input re-renders the form with an error message.

## Template

New `app/templates/settings.html` extending `base.html`:

- Form POSTing to `/settings`
- Labeled number input for "New cards per day", pre-filled with current value, `min="0"`
- Submit button
- Link back to home

`home.html` gains a link to `/settings`.

## Cleanup

- Remove `NEW_CARDS_PER_DAY` from `.env.example`.

## Test Plan

### `test_db.py`

- `get_setting` returns default when key is not set.
- `get_setting` returns stored value after `set_setting`.
- `set_setting` upserts (overwrites existing value).

### `test_routes.py`

- `GET /settings` renders the current `new_cards_per_day` value.
- `POST /settings` updates the value and redirects to `/settings`.
- `POST /settings` with invalid input (non-numeric, negative) re-renders with error.
- Home and session routes respect the DB-stored setting.
- Migrate existing `test_home_shows_new_count` from `monkeypatch.setattr(routes, "_NEW_CARDS_PER_DAY", 1)` to `db.set_setting("new_cards_per_day", "1")`.
