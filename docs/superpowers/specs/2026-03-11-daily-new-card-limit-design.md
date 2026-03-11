# Daily New Card Limit — Design Spec

## Problem

When WaniKani sync runs, all passed kanji get cards with `due=now`, so they all enter the review queue immediately. A user who has passed hundreds of kanji gets overwhelmed on first sync.

## Solution

Gate how many never-reviewed ("new") cards appear in each day's review queue. Cards already in the FSRS review cycle are unaffected — only new introductions are limited.

## Configuration

- Environment variable: `NEW_CARDS_PER_DAY` (integer, default `20`)
- Read once at app startup in `main.py`, stored as module-level in `app/db.py` (or passed through)
- Validation at startup: must be a non-negative integer. Invalid values (non-integer, negative) raise `ValueError` and prevent app from starting.

## Definitions

- **New card**: a row in `cards` where `last_review IS NULL`
- **Review card**: a row in `cards` where `last_review IS NOT NULL`
- **Introduced today**: a kanji whose earliest row in `reviews` has `reviewed_at >= <today-start-utc>` — meaning its first-ever review happened today (UTC)
- **Today start**: `datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()`

## Logic

`get_due_kanji()` currently returns all cards where `due <= now`. The new behavior:

1. **Review cards** (due and `last_review IS NOT NULL`): always included, no limit.
2. **Count already introduced today**: `SELECT COUNT(DISTINCT kanji) FROM reviews WHERE kanji IN (SELECT kanji FROM reviews GROUP BY kanji HAVING MIN(reviewed_at) >= ?)` with today-start as param.
3. **Remaining new slots**: `max(0, NEW_CARDS_PER_DAY - already_introduced_today)`.
4. **New cards**: select up to `remaining_slots` cards where `due <= now AND last_review IS NULL`. No particular ordering required.
5. **Return**: review cards + new cards combined.

`due_count()` returns a `tuple[int, int]` of `(total_due, new_due)` so the home page can display both. It follows the same gating logic as `get_due_kanji()`.

**Session ordering:** `start_session()` continues to shuffle all due kanji together.

## UI Change

Home page text changes from:

> 5 cards due for review.

To:

> 5 cards due for review (2 new).

## Files Changed

- `app/db.py` — modify `get_due_kanji()` and `due_count()`, add `_new_introduced_today()` helper, add `_new_cards_per_day` module var with setter
- `app/routes.py` — pass `new_count` to home template
- `app/templates/home.html` — display new count
- `main.py` — read `NEW_CARDS_PER_DAY` from env, pass to db module
- `.env.example` — add `NEW_CARDS_PER_DAY=20`
- `tests/test_db.py` — new tests for limit behavior
- `tests/test_routes.py` — update home page test for new display

## Edge Cases

- `NEW_CARDS_PER_DAY=0`: no new cards introduced, only reviews.
- All cards are new (first day): returns up to the daily limit.
- User reviews a new card, then starts another session same day: that card is now "introduced today" and counts toward the limit, not re-counted as new.
- Limit higher than available new cards: all available new cards are returned.
- Limit changed between app restarts mid-day: works naturally since "introduced today" is computed from reviews, independent of the config value.
