import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import Database
from app.routes import router


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.db = Database(os.getenv("DB_PATH", "stroke-memorize.db"))
    yield
    application.state.db.close()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(router)
