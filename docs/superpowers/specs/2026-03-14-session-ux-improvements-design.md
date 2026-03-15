# Session UX Improvements Design

## Overview

Three improvements to the review session experience: a "Go Home" button for quitting mid-session, bidirectional stroke navigation, and keyboard controls for the stroke animation.

## Feature 1: Go Home Button

### Problem
Users cannot quit a review session partway through — they must complete all cards or navigate away manually.

### Design
Add a "Go Home" link to `_card_partial.html`, placed below the rating buttons, styled as a button. It links to `/` with a plain `<a>` tag.

No backend changes are needed. Reviews are already persisted on each rating click, so leaving mid-session loses no progress. The in-memory session queue is simply abandoned.

### Files Changed
- `app/templates/_card_partial.html`

## Feature 2: Prev/Next Stroke Controls

### Problem
The stroke animation only moves forward. Users cannot step back to re-examine a previous stroke.

### Design
Add a `prevStroke()` function to `strokes.js` that:
- Early-returns if `_strokeIndex` is already 0 (no-op, mirrors the guard in `nextStroke()`)
- Decrements `_strokeIndex`
- Hides the stroke at the new index (opacity → 0, label → hidden)
- Updates the stroke counter display
- Disables the Prev button when `_strokeIndex` reaches 0
- Enables the Next button (since we moved back from total or stayed below it)

Update `nextStroke()` to similarly manage both buttons: enable Prev when moving forward from 0, disable Next when reaching total.

Add a "Prev" button to `strokes.html` with `id="prev-stroke-btn"` and `onclick="prevStroke()"`, next to the existing "Next Stroke" button, initially disabled.

**Index semantics:** `_strokeIndex` always points one past the last visible stroke (0 = none visible, total = all visible). `nextStroke()` shows the stroke at `_strokeIndex` then increments. `prevStroke()` decrements first, then hides the stroke at the new `_strokeIndex`.

### Files Changed
- `app/static/strokes.js`
- `app/templates/strokes.html`

## Feature 3: Keyboard Controls

### Problem
Users must click buttons to navigate strokes. Keyboard control would be faster and more natural.

### Design
There are two separate keyboard concerns with different lifecycles:

**Arrow keys (Left/Right):** Register a `keydown` listener on `document` inside `initStrokes()`, mapping `ArrowLeft` → `prevStroke()` and `ArrowRight` → `nextStroke()`. These simply delegate to the existing functions, which have their own boundary guards — no additional bounds checking needed. Since the listener is registered inside `initStrokes()`, arrow keys are only active after strokes are loaded.

To prevent listener accumulation across cards (since HTMX swaps in fresh partials and `initStrokes()` is called per card), use an `AbortController`: store a module-level controller, abort the previous one at the start of each `initStrokes()` call, then pass the new controller's signal to `addEventListener`.

**Spacebar:** Register a persistent `keydown` listener at script load time (top-level in `strokes.js`). On `Space`, look for `#show-strokes-btn` (add this ID to the "Show Strokes" button in `_card_partial.html`). If the button exists, click it and `preventDefault()`. If the button doesn't exist (strokes already showing, or not on card page), do nothing. This listener is never removed — it's a single persistent listener that's inert when there's no target button. Since HTMX swaps in a fresh `_card_partial.html` for each new card (which includes a new `#show-strokes-btn`), the same listener naturally works across cards.

All keyboard listeners call `preventDefault()` to suppress default browser behavior (scrolling).

### Files Changed
- `app/static/strokes.js`

## Summary of All Files Changed

| File | Features |
|------|----------|
| `app/templates/_card_partial.html` | Go Home button, `id="show-strokes-btn"` on Show Strokes button |
| `app/static/strokes.js` | Prev stroke, keyboard controls |
| `app/templates/strokes.html` | Prev button |

No backend/route changes. No new files. No database changes.
