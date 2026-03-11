from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import app.db as db

templates = Jinja2Templates(directory="app/templates")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    count = db.due_count()
    return templates.TemplateResponse(
        request, "home.html", {"due_count": count}
    )
