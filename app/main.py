from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import connect, disconnect, run_migrations
from app.routers import api_keys, auth, badges, blog, challenges, developer_profiles, events, feedback, leaderboard, organizations, projects, proxy, scores, sessions, share, submissions

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
    description="Backend API for Kodwai - AI-Agent Coding Platform",
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
app.include_router(challenges.router, prefix="/api")
app.include_router(submissions.router, prefix="/api")
app.include_router(leaderboard.router, prefix="/api")
app.include_router(developer_profiles.router, prefix="/api")
app.include_router(badges.router, prefix="/api")
app.include_router(feedback.router, prefix="/api")
app.include_router(share.router, prefix="/api")
app.include_router(blog.router, prefix="/api")
app.include_router(events.router, prefix="/api")

# Admin routers
from app.routers.admin import auth as admin_auth, dashboard as admin_dashboard, users as admin_users, challenges as admin_challenges
from app.routers.admin import organizations as admin_orgs, sessions as admin_sessions, submissions as admin_submissions, analytics as admin_analytics, projects as admin_projects
from app.routers.admin import badges as admin_badges, api_keys as admin_api_keys, system as admin_system, leaderboard as admin_leaderboard, feedback as admin_feedback
from app.routers.admin import blog as admin_blog, blog_images as admin_blog_images
from app.routers.admin import events as admin_events
app.include_router(admin_auth.router, prefix="/api/admin")
app.include_router(admin_dashboard.router, prefix="/api/admin")
app.include_router(admin_users.router, prefix="/api/admin")
app.include_router(admin_challenges.router, prefix="/api/admin")
app.include_router(admin_orgs.router, prefix="/api/admin")
app.include_router(admin_sessions.router, prefix="/api/admin")
app.include_router(admin_submissions.router, prefix="/api/admin")
app.include_router(admin_analytics.router, prefix="/api/admin")
app.include_router(admin_projects.router, prefix="/api/admin")
app.include_router(admin_badges.router, prefix="/api/admin")
app.include_router(admin_api_keys.router, prefix="/api/admin")
app.include_router(admin_system.router, prefix="/api/admin")
app.include_router(admin_leaderboard.router, prefix="/api/admin")
app.include_router(admin_feedback.router, prefix="/api/admin")
app.include_router(admin_blog.router, prefix="/api/admin")
app.include_router(admin_blog_images.router, prefix="/api/admin")
app.include_router(admin_events.router, prefix="/api/admin")


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}
