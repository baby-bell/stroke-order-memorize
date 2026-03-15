# Session UX Improvements Design

## Overview

Three improvements to the review session experience: a "Go Home" button for quitting mid-session, bidirectional stroke navigation, and keyboard controls for the stroke animation.

## Feature 1: Go Home Button

### Problem
Users cannot quit a review session partway through — they must complete all cards or navigate away manually.

### Design
Add a "Go Home" link to `_card_partial.html`, styled as a button. It links to `/` with a plain `<a>` tag.

No backend changes are needed. Reviews are already persisted on each rating click, so leaving mid-session loses no progress. The in-memory session queue is simply abandoned.

### Files Changed
- `app/templates/_card_partial.html`

## Feature 2: Prev/Next Stroke Controls

### Problem
The stroke animation only moves forward. Users cannot step back to re-examine a previous stroke.

### Design
Add a `prevStroke()` function to `strokes.js` that:
- Decrements `_strokeIndex`
- Hides the stroke at the new index (opacity → 0, label → hidden)
- Updates the stroke counter display

Update `nextStroke()` to also manage the Prev button's disabled state. Both buttons manage each other's disabled state at boundaries (Prev disabled at 0, Next disabled at total).

Add a "Prev" button to `strokes.html` next to the existing "Next Stroke" button, initially disabled.

### Files Changed
- `app/static/strokes.js`
- `app/templates/strokes.html`

## Feature 3: Keyboard Controls

### Problem
Users must click buttons to navigate strokes. Keyboard control would be faster and more natural.

### Design
**Arrow keys (Left/Right):** Register a `keydown` listener on `document` inside `initStrokes()`, mapping `ArrowLeft` → `prevStroke()` and `ArrowRight` → `nextStroke()`. Since the listener is registered inside `initStrokes()`, it is only active after strokes are loaded.

**Spacebar:** Register a separate `keydown` listener at script load time that listens for `Space` and clicks the "Show Strokes" button. This listener removes itself once fired so spacebar doesn't interfere after strokes are visible.

Both listeners call `preventDefault()` to suppress default browser behavior (scrolling).

### Files Changed
- `app/static/strokes.js`

## Summary of All Files Changed

| File | Features |
|------|----------|
| `app/templates/_card_partial.html` | Go Home button |
| `app/static/strokes.js` | Prev stroke, keyboard controls |
| `app/templates/strokes.html` | Prev button |

No backend/route changes. No new files. No database changes.
