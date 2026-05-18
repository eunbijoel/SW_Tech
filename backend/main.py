"""
FastAPI application entry point.
Run: uvicorn backend.main:app --reload
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.core.config import settings
from backend.core.logging import configure_logging, get_logger
from backend.api.routes import chat, files, models, execution, history

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    log.info("Starting AI Prompt Platform", version=settings.APP_VERSION)
    settings.ensure_dirs()
    yield
    log.info("Shutting down AI Prompt Platform")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url=f"{settings.API_PREFIX}/docs",
    redoc_url=f"{settings.API_PREFIX}/redoc",
    openapi_url=f"{settings.API_PREFIX}/openapi.json",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
prefix = settings.API_PREFIX
app.include_router(chat.router,      prefix=f"{prefix}/chat",      tags=["Chat"])
app.include_router(files.router,     prefix=f"{prefix}/files",     tags=["Files"])
app.include_router(models.router,    prefix=f"{prefix}/models",    tags=["Models"])
app.include_router(execution.router, prefix=f"{prefix}/execution", tags=["Execution"])
app.include_router(history.router,   prefix=f"{prefix}/history",   tags=["History"])


@app.get("/health", tags=["Health"])
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": settings.APP_VERSION})
