"""CreditLens API entrypoint.   Run:  uvicorn app.main:app --reload"""
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import db
from app.config import get_settings
from app.routers import auth, dashboard, meta, offers, scores
from app.services.scoring import get_model

log = logging.getLogger("creditlens")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.jwt_secret == "dev-only-change-me":
        if s.env == "production":
            raise RuntimeError("Set CREDITLENS_JWT_SECRET before running with CREDITLENS_ENV=production.")
        log.warning("CREDITLENS_JWT_SECRET is not set; using an insecure development secret.")
    db.init_db(s.db_path)
    get_model()  # load once at startup so a missing/corrupt model fails fast
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(
        title="CreditLens API",
        version="1.0.0",
        description="Explainable alternative credit score demo (synthetic data, not a real credit score).",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(meta.router)
    app.include_router(auth.router)
    app.include_router(scores.router)
    app.include_router(offers.router)
    app.include_router(dashboard.router)
    # Serve the bundled frontend (plain static files, no build step) at "/" if present.
    # Mounted last so API routes always win.
    if os.path.isdir(s.frontend_dir):
        app.mount("/", StaticFiles(directory=s.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
