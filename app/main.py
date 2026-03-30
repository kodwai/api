from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect, disconnect, run_migrations
from app.routers import api_keys, auth, organizations, projects, proxy, scores, sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize DB and run migrations on startup, disconnect on shutdown."""
    logger.info("Starting up Kodwai API...")
    connect()
    run_migrations()
    logger.info("Database initialized and migrations applied")

    from app.services.session_cleanup import start_session_cleanup
    start_session_cleanup()

    yield
    logger.info("Shutting down Kodwai API...")
    from app.routers.proxy import http_client
    await http_client.aclose()
    disconnect()


app = FastAPI(
    title="Kodwai API",
    description="Backend API for Kodwai - AI Interview Platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001", *settings.cors_origins_list],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(api_keys.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(scores.router, prefix="/api")
app.include_router(proxy.router, prefix="/api")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
