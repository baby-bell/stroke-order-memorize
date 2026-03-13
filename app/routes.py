import os
import random
import uuid
from datetime import datetime, timezone
from typing import Annotated

import httpx
from fastapi import APIRouter, Cookie, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fsrs import Rating, Scheduler

import app.db as db
from app.strokes import parse_strokes
from app.wanikani import fetch_subjects, fetch_passed_assignments

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()

# Server-side session store: session_id -> ordered list of kanji to review
_sessions: dict[str, list[str]] = {}


def _queue(session_id: str | None) -> list[str]:
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    return []


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    total, new = db.due_count()
    return templates.TemplateResponse(
        request, "home.html", {"due_count": total, "new_count": new}
    )


@router.post("/sync", response_class=HTMLResponse)
async def do_sync(request: Request):
    api_key = os.getenv("WANIKANI_API_KEY")
    if not api_key:
        return HTMLResponse("<p>Error: WANIKANI_API_KEY not set in .env</p>")
    try:
        async with httpx.AsyncClient(
            base_url="https://api.wanikani.com",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Wanikani-Revision": "20170710",
            },
        ) as client:
            now = datetime.now(timezone.utc).isoformat()

            subjects_meta = db.get_sync_meta("subjects")
            level_map, new_subjects_meta = await fetch_subjects(client, subjects_meta)
            if level_map is None:
                level_map = db.get_cached_subjects()
            else:
                db.upsert_cached_subjects(level_map)
                level_map = db.get_cached_subjects()  # re-read full merged cache
                if new_subjects_meta:
                    db.set_sync_meta("subjects", now, **new_subjects_meta)

            assignments_meta = db.get_sync_meta("assignments")
            passed_ids, new_assignments_meta = await fetch_passed_assignments(
                client, assignments_meta
            )
            if passed_ids is None:
                return HTMLResponse("<p>Synced 0 kanji.</p>")
            if new_assignments_meta:
                db.set_sync_meta("assignments", now, **new_assignments_meta)

            synced: list[tuple[str, int]] = []
            for subject_id in passed_ids:
                if subject_id not in level_map:
                    continue
                kanji, level = level_map[subject_id]
                db.upsert_character(kanji, level, now)
                db.insert_card_if_new(kanji)
                synced.append((kanji, level))

        return HTMLResponse(f"<p>Synced {len(synced)} kanji.</p>")
    except httpx.HTTPStatusError as exc:
        return HTMLResponse(f"<p>Sync error: HTTP {exc.response.status_code}</p>")


@router.get("/session")
async def start_session(
    session_id: str | None = Cookie(default=None),
):
    due = db.get_due_kanji()
    if not due:
        return RedirectResponse("/session/done", status_code=303)
    random.shuffle(due)
    sid = session_id or str(uuid.uuid4())
    _sessions[sid] = due
    resp = RedirectResponse("/session/card", status_code=303)
    resp.set_cookie("session_id", sid)
    return resp


@router.get("/session/card", response_class=HTMLResponse)
async def session_card(
    request: Request,
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        return RedirectResponse("/session/done", status_code=303)
    return templates.TemplateResponse(
        request, "card.html", {"kanji": queue[0]}
    )


@router.get("/session/strokes", response_class=HTMLResponse)
async def session_strokes(
    request: Request,
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        return HTMLResponse("<p>No active session.</p>")
    strokes = parse_strokes(queue[0])
    return templates.TemplateResponse(
        request, "strokes.html", {"strokes": strokes}
    )


@router.post("/session/review", response_class=HTMLResponse)
async def session_review(
    request: Request,
    rating: Annotated[int, Form()],
    session_id: str | None = Cookie(default=None),
):
    queue = _queue(session_id)
    if not queue:
        resp = HTMLResponse("")
        resp.headers["HX-Redirect"] = "/session/done"
        return resp

    kanji = queue.pop(0)
    card = db.get_card(kanji)
    updated_card, _ = Scheduler().review_card(card, Rating(rating))
    db.update_card(kanji, updated_card)
    db.insert_review(kanji, rating, datetime.now(timezone.utc).isoformat())

    if not queue:
        resp = HTMLResponse("")
        resp.headers["HX-Redirect"] = "/session/done"
        return resp

    return templates.TemplateResponse(
        request, "_card_partial.html", {"kanji": queue[0]}
    )


@router.get("/session/done", response_class=HTMLResponse)
async def session_done(request: Request):
    return templates.TemplateResponse(request, "done.html", {})
