# stroke-memorize: Backend & Frontend Design

## Overview

A single-user local web app for practising Japanese kanji handwriting. The user writes on paper, then reveals the correct stroke order as a slideshow to self-assess. Cards are sourced from the user's WaniKani progress and scheduled with FSRS.

## Stack

- **Backend:** FastAPI + Jinja2 templates
- **Frontend:** HTMX (server-driven partials) + ~10 lines of vanilla JS for the stroke slideshow
- **SRS:** `fsrs` PyPI package (v6+)
- **Stroke data:** `kanjivg` PyPI package (v20250816+) — 11,661 SVGs, one per character
- **WaniKani:** thin `httpx`-based client against API v2 (no PyPI client; v1.2 package is deprecated)
- **Database:** SQLite via Python's built-in `sqlite3`
- **Config:** API key stored in `.env`, read with `python-dotenv`

## Project Structure

```
stroke-memorize/
  main.py                  # FastAPI app factory, entry point
  app/
    routes.py              # all HTTP routes
    wanikani.py            # WaniKani API v2 client (httpx)
    strokes.py             # KanjiVG SVG parser (xml.etree.ElementTree)
    db.py                  # SQLite connection and query helpers
    templates/
      base.html            # layout shell
      home.html            # sync status + start session button
      card.html            # flashcard view
      strokes.html         # HTMX partial: stroke slideshow SVG
      done.html            # end-of-session summary
    static/
      strokes.js           # stroke reveal logic (~10 lines)
  stroke-memorize.db       # SQLite database (gitignored)
  .env                     # WANIKANI_API_KEY (gitignored)
```

## Database Schema

```sql
CREATE TABLE characters (
    kanji       TEXT NOT NULL PRIMARY KEY,
    wk_level    INT  NOT NULL CHECK (wk_level BETWEEN 1 AND 60),
    synced_at   TEXT NOT NULL  -- ISO8601
);

CREATE TABLE cards (
    kanji       TEXT NOT NULL PRIMARY KEY REFERENCES characters(kanji),
    state       INT  NOT NULL DEFAULT 1   CHECK (state IN (1, 2, 3)),  -- 1=Learning 2=Review 3=Relearning
    step        INT  NOT NULL DEFAULT 0   CHECK (step >= 0),
    stability   REAL NOT NULL DEFAULT 0.0 CHECK (stability >= 0.0),
    difficulty  REAL NOT NULL DEFAULT 0.0 CHECK (difficulty >= 0.0),
    due         TEXT NOT NULL,            -- ISO8601
    last_review TEXT                      -- NULL = never reviewed
);

CREATE TABLE reviews (
    id          INTEGER NOT NULL PRIMARY KEY,
    kanji       TEXT    NOT NULL REFERENCES characters(kanji),
    rating      INT     NOT NULL CHECK (rating IN (1, 2, 3, 4)),  -- 1=Again 2=Hard 3=Good 4=Easy
    reviewed_at TEXT    NOT NULL  -- ISO8601
);
```

`stability` and `difficulty` default to 0.0; FSRS initialises them properly on first review. `last_review` is NULL for cards that have never been reviewed.

## Routes

```
GET  /                 → home page (sync status, start session button)
POST /sync             → trigger WaniKani sync; returns HTMX partial updating status

GET  /session          → build session (due cards, shuffled), redirect to /session/card
GET  /session/card     → current card: large kanji + "Show Strokes" button; rating buttons disabled
GET  /session/strokes  → HTMX partial: SVG stroke slideshow for current card
POST /session/review   → body: {rating: 1-4}; update FSRS, write review row, return next card partial
GET  /session/done     → shown when session queue is empty
```

No settings route. The user edits `.env` directly.

## Session State

Session state (queue of due kanji, current position) lives in a server-side dict keyed by a session cookie. Appropriate for single-user local use; no external session store needed.

## Application Flow

1. User visits `/` — sees how many cards are due and a "Start" button.
2. `POST /sync` — fetches `/v2/assignments?subject_type=kanji&passed=true` from WaniKani, upserts into `characters`, creates a `cards` row (with defaults) for any new kanji.
3. `GET /session` — queries `cards WHERE due <= now()`, shuffles, stores in session, redirects to `/session/card`.
4. `GET /session/card` — renders the kanji prominently. "Show Strokes" uses `hx-get="/session/strokes"` to swap in the slideshow. Rating buttons (Again / Hard / Good / Easy) are present but disabled.
5. `GET /session/strokes` — HTMX swaps in the SVG with all stroke paths hidden. JS enables the rating buttons. User clicks through strokes one at a time.
6. `POST /session/review` — calls `fsrs.FSRS().review_card(card, rating)`, writes updated card to `cards`, appends a row to `reviews`, returns next card as HTMX partial (or redirects to `/session/done`).

## Stroke Slideshow

`strokes.py` parses the KanjiVG SVG with `xml.etree.ElementTree`, extracts `<path>` elements in stroke order (by id suffix `-s1`, `-s2`, …), and passes them to the Jinja2 template. The template renders the SVG with all paths at `opacity: 0`. `strokes.js` maintains a counter; each "Next" click sets the next path to `opacity: 1`. Stroke number labels come from the `<text>` elements already present in the KanjiVG SVG.

## WaniKani Client

`wanikani.py` uses `httpx` (async). Two calls:

- `GET /v2/user` — verify API key, fetch username
- `GET /v2/assignments?subject_type=kanji&passed=true&page_after_id=<cursor>` — paginated; follows `pages.next_url` until exhausted

The API key is read from `WANIKANI_API_KEY` in `.env`.

## Dependencies

```toml
dependencies = [
    "fastapi",
    "uvicorn",
    "jinja2",
    "python-multipart",   # for form POST bodies
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
