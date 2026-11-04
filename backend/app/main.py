"""FastAPI 앱. 실행: `uv run uvicorn app.main:app --reload` → http://localhost:8000/docs"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import errors
from .config import get_settings
from .db import init_db


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    from .seed import seed_basics

    seed_basics()
    from .worker import requeue_unfinished

    requeue_unfinished()  # 서버가 꺼질 때 남은 대기·검수 중 건을 다시 넣는다
    from .mail.gmail import start_poller

    start_poller()
    yield


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="회의비 증빙 자동 검수 API", version="0.2.0", lifespan=lifespan,
                  description="인공지능혁신융합대학사업단 회의비 증빙 검수. API 약속은 docs/frontend-api.md v0.2")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    errors.install(app)

    from .api import router

    app.include_router(router, prefix="/api")
    return app


app = create_app()
