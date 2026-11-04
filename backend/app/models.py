"""DB 테이블 (docs/backend-plan.md 4장).

시간은 한국 시간(Asia/Seoul) 기준 naive datetime으로 저장하고, API에서 +09:00을 붙여 내보낸다.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

KST = timezone(timedelta(hours=9))
PROGRAMS = ["club", "aim", "hackathon", "wemeet", "capstone"]


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None, microsecond=0)


def iso(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=KST).isoformat() if dt else None


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("u"))
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String, default="manager")  # manager / admin
    programs: Mapped[list] = mapped_column(JSON, default=list)
    mailbox: Mapped[str | None] = mapped_column(String, nullable=True)  # club_manager / wemeet_manager


class Team(Base):
    __tablename__ = "teams"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # t_<program>_<nnn>
    program: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    strict: Mapped[bool] = mapped_column(Boolean, default=False)
    members: Mapped[list] = mapped_column(JSON, default=list)  # 팀원 이름 (같은 이름 팀이 여러 프로그램에 있을 때 구분용)
    known_senders: Mapped[list] = mapped_column(JSON, default=list)


class RuleSet(Base):
    __tablename__ = "rule_sets"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # rs_<program>_v<n>
    program: Mapped[str] = mapped_column(String, index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft / confirmed
    conditions: Mapped[list] = mapped_column(JSON)
    removed: Mapped[list] = mapped_column(JSON, default=list)
    confirmed_by: Mapped[str | None] = mapped_column(String, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    program: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    mailbox: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    team_id: Mapped[str | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    team_match: Mapped[str] = mapped_column(String, default="none")  # auto / manual / none
    team_match_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    mail_message_id: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    sender_name: Mapped[str] = mapped_column(String, default="")
    sender_email: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(String, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    processing_status: Mapped[str] = mapped_column(String, default="queued")
    processing_error: Mapped[str | None] = mapped_column(String, nullable=True)
    verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    review_status: Mapped[str] = mapped_column(String, default="pending")
    rule_set_id: Mapped[str | None] = mapped_column(ForeignKey("rule_sets.id"), nullable=True)
    model_info: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extracted: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst, onupdate=now_kst)

    team: Mapped[Team | None] = relationship()
    rule_set: Mapped[RuleSet | None] = relationship()
    files: Mapped[list[File]] = relationship(back_populates="submission", order_by="File.order", cascade="all, delete-orphan")
    checks: Mapped[list[Check]] = relationship(order_by="Check.check_id", cascade="all, delete-orphan")
    reply: Mapped[Reply | None] = relationship(cascade="all, delete-orphan", uselist=False)


class File(Base):
    __tablename__ = "files"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: new_id("f"))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    order: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="other")  # minutes / receipt / other
    format: Mapped[str] = mapped_column(String, default="unknown")  # hwp hwpx docx pdf scan image unknown
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String, index=True)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages: Mapped[list] = mapped_column(JSON, default=list)  # [{n, width, height}]
    submission: Mapped[Submission] = relationship(back_populates="files")


class Check(Base):
    __tablename__ = "checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    check_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    by: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    result: Mapped[str] = mapped_column(String)
    ai_result: Mapped[str] = mapped_column(String)
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(String, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    manager_note: Mapped[str | None] = mapped_column(String, nullable=True)


class Reply(Base):
    __tablename__ = "replies"
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String, default="none")
    to_email: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(String, default="")
    body: Mapped[str] = mapped_column(Text, default="")
    internal_notes: Mapped[list] = mapped_column(JSON, default=list)
    edited_by_manager: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)


class UpstageCache(Base):
    __tablename__ = "upstage_cache"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # ie / ocr / solar
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now_kst)
