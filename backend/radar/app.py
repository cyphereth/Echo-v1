"""Main FastAPI application — assembled from domain routers.

Entrypoint: radar.app:app
Run: uvicorn radar.app:app --reload
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.db import init_db, get_session
from .core.auth_api import router as auth_router, current_user  # noqa: F401 (re-export for tests)
from .news.api import router as news_router
from .brand.api import router as brand_router
from .intel.api import router as intel_router
from . import seed as seed_module

log = logging.getLogger(__name__)

_scheduler = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_db()
    session = get_session()
    try:
        seed_module.run(session)
        seed_module.ensure_demo_user(session)   # idempotent: demo login + backfill owners
        seed_module.ensure_default_topics(session)
        from .intel import seed as intel_seed
        intel_seed.ensure_default_directions(session)
    finally:
        session.close()

    # Background auto-collect. Harmless when idle — only runs probes for brands
    # with auto_collect=True (default off), so no surprise API usage.
    global _scheduler
    if os.getenv("ENABLE_SCHEDULER", "1") == "1" and _scheduler is None:
        from .core.scheduler import Scheduler
        from .brand.api import _get_provider, _get_tg_provider
        web_provider = None
        if os.getenv("WEB_SEARCH_API_KEY"):
            from .core.providers.web import WebSearchProvider
            web_provider = WebSearchProvider()
        _scheduler = Scheduler(_get_provider(), tick_sec=int(os.getenv("SCHEDULER_TICK_SEC", "60")),
                               tg_provider=_get_tg_provider(), web_provider=web_provider)
        _scheduler.start()
        log.info("Auto-collect scheduler started (tick=%ss)", _scheduler._tick_sec)

    yield

    # --- shutdown ---
    if _scheduler is not None:
        _scheduler.stop()
        log.info("Auto-collect scheduler stopped")


app = FastAPI(title="Echo API", version="4.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(news_router)
app.include_router(brand_router)
app.include_router(intel_router)


@app.get("/health")
def health():
    return {"status": "ok"}
