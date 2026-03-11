# stroke-memorize: Backend & Frontend Design

## Overview

A single-user local web app for practising Japanese kanji handwriting. The user writes on paper, then reveals the correct stroke order as a slideshow to self-assess. Cards are sourced from the user's WaniKani progress and scheduled with FSRS.

## Stack

- **Backend:** FastAPI + Jinja2 templates
- **Frontend:** HTMX (server-driven partials) + ~15 lines of vanilla JS for the stroke slideshow
- **SRS:** `fsrs` PyPI package (v6+) — scheduler class is `fsrs.Scheduler`, not `fsrs.FSRS`
- **Stroke data:** `kanjivg` PyPI package (v20250816+) — 11,661 SVGs, one per character
- **WaniKani:** thin `httpx`-based async client against API v2 (no PyPI client; v1.2 package is deprecated)
- **Database:** SQLite via Python's built-in `sqlite3`
- **Config:** API key stored in `.env`, read with `python-dotenv`

## Project Structure

```
stroke-memorize/
  main.py                  # FastAPI app factory, entry point; calls db.init() on startup
  app/
    routes.py              # all HTTP routes
    wanikani.py            # WaniKani API v2 client (httpx)
    strokes.py             # KanjiVG SVG parser (xml.etree.ElementTree)
    db.py                  # SQLite connection, CREATE TABLE IF NOT EXISTS on import, query helpers
    templates/
      base.html            # layout shell
      home.html            # sync status + start session button
      card.html            # full flashcard page (wraps _card_partial.html)
      _card_partial.html   # HTMX partial: card content reused by card.html and POST /session/review
      strokes.html         # HTMX partial: stroke slideshow SVG
      done.html            # end-of-session summary
    static/
      strokes.js           # stroke reveal + rating button enable logic
  stroke-memorize.db       # SQLite database (gitignored)
  .env                     # WANIKANI_API_KEY (gitignored)
```

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS characters (
    kanji       TEXT NOT NULL PRIMARY KEY,
    wk_level    INT  NOT NULL CHECK (wk_level BETWEEN 1 AND 60),
    synced_at   TEXT NOT NULL  -- ISO8601
);

CREATE TABLE IF NOT EXISTS cards (
    kanji       TEXT    NOT NULL PRIMARY KEY REFERENCES characters(kanji),
    state       INT     NOT NULL DEFAULT 0 CHECK (state IN (0, 1, 2, 3)),  -- 0=New 1=Learning 2=Review 3=Relearning
    step        INT,                       -- NULL when card is in Review state (state=2)
    stability   REAL,                      -- NULL for unreviewed cards; FSRS initialises on first review
    difficulty  REAL,                      -- NULL for unreviewed cards; FSRS initialises on first review
    due         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),  -- new cards due immediately
    last_review TEXT                       -- NULL = never reviewed
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER NOT NULL PRIMARY KEY,
    kanji       TEXT    NOT NULL REFERENCES characters(kanji),
    rating      INT     NOT NULL CHECK (rating IN (1, 2, 3, 4)),  -- 1=Again 2=Hard 3=Good 4=Easy
    reviewed_at TEXT    NOT NULL  -- ISO8601
);
```

`db.py` runs these statements on module import so the schema is always present on first run. `stability`, `difficulty`, and `step` are nullable because FSRS initialises them on the first review; storing `0.0` would cause the scheduler to skip initialisation. When reconstructing an `fsrs.Card` from a DB row, `None` must be passed for these fields if the stored value is `NULL`.

## Routes

```
GET  /                 → home page (sync status, due count, start session button)
POST /sync             → trigger WaniKani sync; returns HTMX partial updating status

GET  /session          → build session (due cards, shuffled), store in session cookie dict;
                         redirect to /session/card; redirect to /session/done if queue is empty
GET  /session/card     → full page: renders base.html wrapping _card_partial.html
GET  /session/strokes  → HTMX partial (hx-target="#card-body"): SVG stroke slideshow
POST /session/review   → body: rating=1..4; update FSRS + write review row;
                         returns _card_partial.html as HTMX partial (hx-target="#card-body"),
                         or redirects to /session/done when queue exhausted

GET  /session/done     → shown when session queue is empty
```

No settings route. The user edits `.env` directly.

HTMX swap targets:
- `POST /sync` → `hx-target="#sync-status"`, `hx-swap="innerHTML"`
- `GET /session/strokes` → `hx-target="#card-body"`, `hx-swap="innerHTML"`
- `POST /session/review` → `hx-target="#card-body"`, `hx-swap="innerHTML"`

The `#card-body` div lives inside `base.html` and is the shared swap target for both the initial card content and the stroke reveal. `_card_partial.html` is the reusable fragment rendered by both `GET /session/card` (via `card.html`) and `POST /session/review` directly.

## Session State

Session state (ordered queue of due kanji strings, current index) lives in a server-side dict keyed by a session cookie value. Appropriate for single-user local use; no external session store needed.

## Application Flow

1. User visits `/` — sees how many cards are due and a "Start" button.
2. `POST /sync` — fetches the user's learned kanji from WaniKani (see WaniKani Client section), upserts into `characters`, creates a `cards` row (with defaults) for any new kanji. Returns an HTML fragment updating `#sync-status`.
3. `GET /session` — queries `cards WHERE due <= now()`, shuffles, stores list in session. If empty, redirects to `/session/done`. Otherwise redirects to `/session/card`.
4. `GET /session/card` — renders the full page with `_card_partial.html` embedded: kanji displayed prominently, "Show Strokes" button (`hx-get="/session/strokes" hx-target="#card-body"`), rating buttons (Again / Hard / Good / Easy) present but `disabled`.
5. `GET /session/strokes` — returns `strokes.html` partial which swaps into `#card-body`: SVG with all stroke paths hidden (`opacity:0`). On load, JS enables the rating buttons.
6. User steps through strokes via "Next Stroke" button. JS reveals paths one at a time.
7. `POST /session/review` — converts `rating` form field to `fsrs.Rating(int(rating))`, calls `fsrs.Scheduler().review_card(card, rating)`, writes updated card back to `cards`, appends row to `reviews`. Returns next `_card_partial.html` as HTMX partial, or redirects to `/session/done`.

## Stroke Slideshow (`strokes.py` + `strokes.js`)

### SVG structure

KanjiVG SVGs contain two sibling `<g>` elements:
- `kvg:StrokePaths_*` — contains `<path>` elements, one per stroke, with ids like `kvg:04e00-s1`, `kvg:04e00-s2`, …
- `kvg:StrokeNumbers_*` — contains `<text>` elements with stroke number labels, at the same index positions

### File lookup

Files are stored in the `kanji/` directory inside the `kanjivg` package, named by zero-padded 5-digit hex Unicode codepoint:

```python
import pathlib, site

def svg_path_for(char: str) -> pathlib.Path:
    codepoint = format(ord(char), '05x')
    for sp in site.getsitepackages():
        p = pathlib.Path(sp) / 'kanji' / f'{codepoint}.svg'
        if p.exists():
            return p
    raise FileNotFoundError(f'No KanjiVG SVG for {char!r}')
```

Prefer the non-Kaisho file (no `-Kaisho` suffix) as the default.

### Parsing

`strokes.py` parses with `xml.etree.ElementTree`, extracts both `<path>` elements (from `StrokePaths`) and `<text>` elements (from `StrokeNumbers`) in order, and passes them as a list of `(path_d, label_text, label_x, label_y)` tuples to the Jinja2 template.

### JS behaviour (`strokes.js`)

Two responsibilities:
1. **On load:** enable the disabled rating buttons once `strokes.html` is swapped in.
2. **Stroke advance:** maintain a counter starting at 0; each "Next Stroke" button click increments the counter and sets the corresponding `<path>`'s `opacity` to `1` and shows the matching stroke number label.

## WaniKani Client (`wanikani.py`)

Uses `httpx.AsyncClient`. Three calls, all authenticated with `Authorization: Bearer <WANIKANI_API_KEY>`:

1. `GET /v2/user` — verify the API key, fetch username for display.
2. `GET /v2/subjects?types=kanji` (paginated) — fetch all kanji subjects to get `id → level` mapping.
3. `GET /v2/assignments?subject_type=kanji&passed_at=true` (paginated, note: filter is `passed_at`, not `passed`) — fetch all passed kanji assignments.

The level for each assignment comes from joining `assignment.subject_id` against the subjects map from step 2. Both paginated endpoints follow `pages.next_url` until it is `null`.

On sync, for each passed kanji:
- Upsert into `characters` (kanji character, wk_level, current timestamp).
- Insert into `cards` with defaults if no row exists yet (i.e., do not overwrite existing FSRS state).

## Dependencies

```toml
dependencies = [
    "fastapi",
    "uvicorn",
    "jinja2",
    "python-multipart",   # required for form POST bodies in FastAPI
    "httpx",
    "python-dotenv",
    "fsrs",
    "kanjivg",
]
```

## Running Locally

```bash
uv run uvicorn main:app --reload
```

## Gitignore

Ensure `.gitignore` includes:
```
stroke-memorize.db
.env
.superpowers/
```
