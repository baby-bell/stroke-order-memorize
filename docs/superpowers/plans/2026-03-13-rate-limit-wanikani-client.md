# Rate-Limit WaniKani API Client Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce max 1 request per second to the WaniKani API, without module-level mutable state.

**Architecture:** Add a `make_client(api_key)` factory in `app/wanikani.py` that returns an `httpx.AsyncClient` with a rate-limiting request event hook. The hook uses a closure over an `asyncio.Lock` and a `float` timestamp — state is scoped to the client instance lifetime. `routes.py` switches to using the factory instead of constructing the client directly.

**Tech Stack:** Python asyncio, httpx event hooks

---

## File Structure

- **Modify:** `app/wanikani.py` — add `make_client()` factory function with rate-limiting event hook
- **Modify:** `app/routes.py` — replace inline `httpx.AsyncClient(...)` with `make_client()`
- **Modify:** `tests/test_wanikani.py` — add rate-limit test, update `wk_client` fixture to use `make_client()`
- **Create:** None

---

## Chunk 1: Rate-Limiting Client Factory

### Task 1: Add rate-limit test

**Files:**
- Modify: `tests/test_wanikani.py`

- [ ] **Step 1: Write the failing test**

Add a test that creates a client via `make_client` with injected fake `clock` and `sleep` callables, fires two rapid requests, and verifies the hook called `sleep` with the correct delay. The fake clock returns 100.0 on the first call (1st request timestamp), 100.3 on the second (2nd request check — only 0.3s elapsed), and 101.3 on the third (2nd request timestamp after sleep). The hook should sleep for 0.7s.

```python
from app.wanikani import make_client

@respx.mock
@pytest.mark.asyncio
async def test_rate_limiter_enforces_one_rps():
    """make_client sleeps to enforce >= 1s between requests."""
    respx.get(f"{BASE}/v2/user").mock(
        return_value=httpx.Response(200, json={"data": {"username": "u", "level": 1}})
    )
    clock_values = iter([100.0, 100.3, 101.3])
    sleep_args = []

    async def fake_sleep(duration):
        sleep_args.append(duration)

    async with make_client("fake-key", clock=lambda: next(clock_values), sleep=fake_sleep) as client:
        await fetch_user(client)
        await fetch_user(client)
    assert sleep_args == [pytest.approx(0.7)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wanikani.py::test_rate_limiter_enforces_one_rps -v`
Expected: FAIL — `ImportError: cannot import name 'make_client'`

### Task 2: Implement `make_client` factory

**Files:**
- Modify: `app/wanikani.py`

- [ ] **Step 3: Implement `make_client`**

Add this function to `app/wanikani.py`. It builds an `httpx.AsyncClient` with auth headers, the API revision header, and a rate-limiting request event hook. The hook uses an `asyncio.Lock` and a closed-over `last_request_time` list (single-element mutable container) to enforce a minimum 1-second gap between requests. This complements the existing `_request_with_retry` 429-handling logic — proactive rate limiting prevents hitting the limit, while the retry logic is a safety net.

The `clock` and `sleep` callables are injected as parameters (defaulting to `time.monotonic` and `asyncio.sleep`) so tests can supply fakes without patching.

Add `import time` to the file's imports section (next to the existing `import asyncio`).

```python
import time
from collections.abc import Callable, Awaitable

def make_client(
    api_key: str,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.AsyncClient:
    """Create a WaniKani API client with 1 RPS rate limiting."""
    lock = asyncio.Lock()
    last_request_time = [0.0]

    async def _rate_limit_hook(request: httpx.Request) -> None:
        async with lock:
            now = clock()
            elapsed = now - last_request_time[0]
            if elapsed < 1.0:
                await sleep(1.0 - elapsed)
            last_request_time[0] = clock()

    return httpx.AsyncClient(
        base_url=_WANIKANI_BASE,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Wanikani-Revision": "20170710",
        },
        event_hooks={"request": [_rate_limit_hook]},
    )
```

- [ ] **Step 4: Run the rate-limit test to verify it passes**

Run: `uv run pytest tests/test_wanikani.py::test_rate_limiter_enforces_one_rps -v`
Expected: PASS (instant — clock is mocked)

- [ ] **Step 5: Run all wanikani tests to check nothing broke**

Run: `uv run pytest tests/test_wanikani.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/wanikani.py tests/test_wanikani.py
git commit -m "feat: add make_client factory with 1 RPS rate limiting"
```

### Task 3: Update `wk_client` fixture to use `make_client`

**Files:**
- Modify: `tests/test_wanikani.py`

- [ ] **Step 7: Update the `wk_client` fixture**

Replace the existing fixture that manually constructs `httpx.AsyncClient` with one that uses `make_client`. To avoid the 1-second delay slowing down all existing tests, patch `asyncio.sleep` in wanikani module for the fixture (or accept the delay — it's a small test suite). The simplest approach: keep the existing fixture as-is since it tests the API functions in isolation. The rate-limit test already uses `make_client` directly. No change needed here.

**Decision: Skip this step.** The existing fixture tests API functions independently of the client factory, which is the correct separation. The rate-limit behavior is covered by its own dedicated test.

### Task 4: Wire `make_client` into routes

**Files:**
- Modify: `app/routes.py`

- [ ] **Step 8: Replace inline client construction with `make_client`**

In `app/routes.py`, replace:

```python
async with httpx.AsyncClient(
    base_url="https://api.wanikani.com",
    headers={
        "Authorization": f"Bearer {api_key}",
        "Wanikani-Revision": "20170710",
    },
) as client:
```

With:

```python
from app.wanikani import make_client

async with make_client(api_key) as client:
```

**Do not remove `import httpx`** from `routes.py` — it is still needed for the `except httpx.HTTPStatusError` handler on line 108.

- [ ] **Step 9: Run the full test suite**

Run: `uv run pytest -v`
Expected: All tests pass

- [ ] **Step 10: Commit**

```bash
git add app/routes.py
git commit -m "refactor: use make_client factory in routes for rate-limited API calls"
```
