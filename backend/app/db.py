"""SQLAlchemy 엔진·세션. DATABASE_URL만 바꾸면 Postgres로 옮길 수 있게 SQLite 전용 기능은 쓰지 않는다."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_Session: sessionmaker | None = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            from pathlib import Path

            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=args)
        _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def reset_engine():
    """테스트에서 DATABASE_URL을 바꾼 뒤 부른다."""
    global _engine, _Session
    if _engine is not None:
        _engine.dispose()
    _engine = _Session = None


def session() -> Session:
    engine()
    return _Session()


def get_db() -> Iterator[Session]:
    db = session()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  테이블 등록

    Base.metadata.create_all(engine())
