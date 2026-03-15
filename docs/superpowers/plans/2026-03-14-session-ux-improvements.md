# Session UX Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Go Home" button to quit mid-session, bidirectional stroke navigation, and keyboard controls for strokes.

**Architecture:** All changes are frontend-only — two templates and one JS file. No backend, route, or database changes. Reviews are already persisted per-click, so mid-session exit is inherently safe.

**Tech Stack:** Jinja2 templates, vanilla JS, HTMX

**Spec:** `docs/superpowers/specs/2026-03-14-session-ux-improvements-design.md`

---

## Chunk 1: Go Home Button and Template Prep

### Task 1: Add Go Home button and Show Strokes button ID

**Files:**
- Modify: `app/templates/_card_partial.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write failing test for Go Home link**

Add to `tests/test_routes.py`:

```python
@pytest.mark.asyncio
async def test_session_card_has_go_home_link(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert 'href="/"' in resp.text
    assert "Go Home" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_routes.py::test_session_card_has_go_home_link -v`
Expected: FAIL — "Go Home" not in response text

- [ ] **Step 3: Write failing test for Show Strokes button ID**

Add to `tests/test_routes.py`:

```python
@pytest.mark.asyncio
async def test_session_card_show_strokes_has_id(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/card")
    assert 'id="show-strokes-btn"' in resp.text
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_routes.py::test_session_card_show_strokes_has_id -v`
Expected: FAIL — id not found

- [ ] **Step 5: Update `_card_partial.html`**

Replace full contents of `app/templates/_card_partial.html` with:

```html
<div class="kanji-display" lang="ja">{{ kanji }}</div>
<div id="stroke-area">
  <button id="show-strokes-btn"
          hx-get="/session/strokes"
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
<p style="text-align:center;margin-top:1.5rem;">
  <a href="/"><button type="button">Go Home</button></a>
</p>
```

- [ ] **Step 6: Run both tests to verify they pass**

Run: `uv run pytest tests/test_routes.py::test_session_card_has_go_home_link tests/test_routes.py::test_session_card_show_strokes_has_id -v`
Expected: both PASS

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add app/templates/_card_partial.html tests/test_routes.py
git commit -m "feat: add Go Home button and show-strokes-btn ID to card partial"
```

---

## Chunk 2: Prev/Next Stroke Controls

### Task 2: Add `prevStroke()` and update `nextStroke()` button management

**Files:**
- Modify: `app/static/strokes.js`
- Modify: `app/templates/strokes.html`
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Write failing test for Prev button in strokes HTML**

Add to `tests/test_routes.py`:

```python
@pytest.mark.asyncio
async def test_session_strokes_has_prev_button(client, fresh_db):
    fresh_db.upsert_character("一", 1, now_iso())
    fresh_db.insert_card_if_new("一")
    await client.get("/session", follow_redirects=True)
    resp = await client.get("/session/strokes")
    assert 'id="prev-stroke-btn"' in resp.text
    assert "prevStroke()" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_routes.py::test_session_strokes_has_prev_button -v`
Expected: FAIL

- [ ] **Step 3: Update `strokes.html` to add Prev button**

Replace full contents of `app/templates/strokes.html` with:

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
<button id="prev-stroke-btn" onclick="prevStroke()" disabled>Prev</button>
<button id="next-stroke-btn" onclick="nextStroke()">Next Stroke</button>
<script>initStrokes({{ strokes|length }});</script>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_routes.py::test_session_strokes_has_prev_button -v`
Expected: PASS

- [ ] **Step 5: Implement `prevStroke()` and update `nextStroke()` / `initStrokes()`**

Replace full contents of `app/static/strokes.js` with:

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
  const prevBtn = document.getElementById('prev-stroke-btn');
  if (prevBtn) prevBtn.disabled = true;
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
  const prevBtn = document.getElementById('prev-stroke-btn');
  if (prevBtn) prevBtn.disabled = false;
}

function prevStroke() {
  if (_strokeIndex <= 0) return;
  _strokeIndex--;
  document.querySelectorAll(`.stroke[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.opacity = '0';
  });
  document.querySelectorAll(`.stroke-label[data-stroke="${_strokeIndex}"]`).forEach(el => {
    el.style.display = 'none';
  });
  const counter = document.getElementById('stroke-count');
  if (counter) counter.textContent = String(_strokeIndex);
  const prevBtn = document.getElementById('prev-stroke-btn');
  if (prevBtn) prevBtn.disabled = _strokeIndex <= 0;
  const nextBtn = document.getElementById('next-stroke-btn');
  if (nextBtn) nextBtn.disabled = false;
}
```

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add app/static/strokes.js app/templates/strokes.html tests/test_routes.py
git commit -m "feat: add prevStroke() and bidirectional stroke navigation"
```

---

## Chunk 3: Keyboard Controls

### Task 3: Add arrow key and spacebar keyboard listeners

**Files:**
- Modify: `app/static/strokes.js`

- [ ] **Step 1: Add arrow key listener in `initStrokes()`**

Add an `AbortController` at module level and wire up arrow keys inside `initStrokes()`. Update `app/static/strokes.js` — add before `function initStrokes(total)`:

```javascript
let _keyController = null;
```

Add at the end of `initStrokes()`, before the closing `}`:

```javascript
  // Arrow key listeners — abort previous to prevent accumulation across HTMX swaps
  if (_keyController) _keyController.abort();
  _keyController = new AbortController();
  document.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowLeft') { e.preventDefault(); prevStroke(); }
    if (e.key === 'ArrowRight') { e.preventDefault(); nextStroke(); }
  }, { signal: _keyController.signal });
```

- [ ] **Step 2: Add persistent spacebar listener at script load time**

Add at the very end of `app/static/strokes.js`:

```javascript
// Spacebar to trigger "Show Strokes" — persistent listener, inert when button absent
document.addEventListener('keydown', (e) => {
  if (e.key !== ' ') return;
  const btn = document.getElementById('show-strokes-btn');
  if (!btn) return;
  e.preventDefault();
  btn.click();
});
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest`
Expected: all tests pass (keyboard behavior is JS-only, no server-side tests needed)

- [ ] **Step 4: Commit**

```bash
git add app/static/strokes.js
git commit -m "feat: add arrow key and spacebar keyboard controls for strokes"
```

- [ ] **Step 5: Manual smoke test**

Run: `uv run uvicorn main:app --reload`

Verify:
1. Start a session with due cards
2. Press Space — strokes should load
3. Press Right arrow — strokes advance one at a time
4. Press Left arrow — strokes go back one at a time
5. Click "Go Home" — returns to home page
6. Start session again — previously reviewed cards should not reappear
