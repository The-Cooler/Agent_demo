from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import chat, sessions, tools
from app.deps import init_db
from app.llm.base import LLMError
from app.sessions.errors import SessionBusy, SessionNotFound

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(lifespan=lifespan)

app.include_router(tools.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.exception_handler(SessionNotFound)
async def session_not_found_handler(
    request: Request, exc: SessionNotFound
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": "session not found"})


@app.exception_handler(SessionBusy)
async def session_busy_handler(request: Request, exc: SessionBusy) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "session is busy"})


@app.exception_handler(LLMError)
async def llm_error_handler(request: Request, exc: LLMError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})
