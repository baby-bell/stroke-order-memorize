import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.db as db
from app.routes import router

load_dotenv()


@asynccontextmanager
async def lifespan(application: FastAPI):
    db.init(os.getenv("DB_PATH", "stroke-memorize.db"))
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
