# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`stroke-memorize` is a Python web app for memorizing stroke order and how to write Japanese kanji. It uses FastAPI + HTMX + SQLite with FSRS spaced repetition scheduling. Cards are sourced from WaniKani and stroke data from KanjiVG.

## Package Manager

This project uses `uv`. Use `uv` for all dependency and environment management:

```bash
uv run main.py          # Run the app
uv add <package>        # Add a dependency
uv run pytest           # Run tests (once pytest is added)
uv run pytest tests/test_foo.py::test_bar  # Run a single test
```

Python version is pinned to 3.14 via `.python-version`.

## Project Structure

- `main.py` — FastAPI app entry point with lifespan, static files, and router
- `app/db.py` — SQLite database layer (characters, cards, reviews tables)
- `app/strokes.py` — KanjiVG SVG parser for stroke order data
- `app/wanikani.py` — WaniKani API v2 client with pagination and sync
- `app/routes.py` — All routes: home, sync, session, card, strokes, review, done
- `app/templates/` — Jinja2 templates (base, home, card, strokes, done, _card_partial)
- `app/static/strokes.js` — Stroke reveal slideshow JS
- `tests/` — pytest test suite
- `pyproject.toml` — project metadata and dependencies

## Commands

- **Run:** `uv run uvicorn main:app --reload`
- **Test all:** `uv run pytest`
- **Single test:** `uv run pytest tests/test_db.py::TestUpsertCharacter -v`
- **Env:** copy `.env.example` to `.env` and fill in `WANIKANI_API_KEY`
