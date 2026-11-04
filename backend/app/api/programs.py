"""S1 목록: 요약 카드, 팀 사이드바, 제출 목록 (+ 프로그램 미확정 목록)."""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import views
from ..db import get_db
from ..errors import ApiError
from ..models import PROGRAMS, Submission, Team, User, iso, now_kst
from ..schemas import ErrorResponse, Summary, SubmissionPage, TeamListItem
from ..security import current_user, require_program

router = APIRouter(prefix="/programs", tags=["programs"])
ERR = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}}


def _program(user: User, program: str):
    if program not in PROGRAMS:
        raise ApiError(404, "PROGRAM_NOT_FOUND", "프로그램을 찾을 수 없습니다.")
    require_program(user, program)


def _submissions(db: Session, user: User, program: str):
    q = select(Submission)
    if program == "unassigned":  # 프로그램 미확정: 로그인한 담당자 메일함으로 온 것만 (관리자는 전부)
        q = q.where(Submission.program.is_(None))
        if user.role != "admin":
            q = q.where(Submission.mailbox == user.mailbox)
    else:
        _program(user, program)
        q = q.where(Submission.program == program)
    return list(db.scalars(q))


@router.get("/{program}/summary", response_model=Summary, responses=ERR)
def summary(program: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    subs = _submissions(db, user, program)
    today = now_kst().date()
    pending_done = [s for s in subs if s.review_status == "pending" and s.processing_status == "done"]
    return {"today_received": sum(s.received_at.date() == today for s in subs),
            "unconfirmed": sum(s.review_status == "pending" for s in subs),
            "ai_review": sum(s.verdict == "review" for s in pending_done),
            "needs_fix": sum(s.verdict == "needs_fix" for s in pending_done),
            "reject": sum(s.verdict == "reject" for s in pending_done),
            "reply_failed": sum(views.reply_status(s) == "failed" for s in subs),
            "processing": sum(s.processing_status in ("queued", "processing") for s in subs)}


@router.get("/{program}/teams", response_model=list[TeamListItem], responses=ERR)
def teams(program: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    _program(user, program)
    subs = _submissions(db, user, program)
    rows = []
    for t in db.scalars(select(Team).where(Team.program == program)):
        mine = [s for s in subs if s.team_id == t.id]
        rows.append({"id": t.id, "name": t.name, "unconfirmed": sum(s.review_status == "pending" for s in mine), "total": len(mine),
                     "last_received_at": iso(max((s.received_at for s in mine), default=None))})
    rows.sort(key=lambda r: (-r["unconfirmed"], r["name"]))
    none = [s for s in subs if s.team_id is None]
    rows.append({"id": None, "name": views.UNASSIGNED_TEAM, "unconfirmed": sum(s.review_status == "pending" for s in none), "total": len(none),
                 "last_received_at": iso(max((s.received_at for s in none), default=None))})
    return rows


@router.get("/{program}/submissions", response_model=SubmissionPage, responses=ERR,
            description="program에 `unassigned`를 넣으면 프로그램 미확정 목록(로그인한 담당자 메일함 것만)")
def submissions(program: str, team_id: str | None = None, verdict: str | None = Query(None, description="쉼표로 여러 개: reject,needs_fix"),
                review_status: str | None = None, reply_status: str | None = None,
                from_: date | None = Query(None, alias="from"), to: date | None = None, q: str | None = None,
                sort: str = Query("default", pattern="^(default|received_desc|received_asc)$"),
                page: int = Query(1, ge=1), size: int = Query(50, ge=1, le=200),
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    subs = _submissions(db, user, program)
    if team_id == "unassigned":
        subs = [s for s in subs if s.team_id is None]
    elif team_id:
        subs = [s for s in subs if s.team_id == team_id]
    if verdict:
        want = set(verdict.split(","))
        subs = [s for s in subs if s.processing_status == "done" and s.verdict in want]
    if review_status:
        subs = [s for s in subs if s.review_status == review_status]
    if reply_status:
        subs = [s for s in subs if views.reply_status(s) in set(reply_status.split(","))]
    if from_:
        subs = [s for s in subs if s.received_at >= datetime.combine(from_, time.min)]
    if to:
        subs = [s for s in subs if s.received_at <= datetime.combine(to, time.max)]
    if q:
        k = q.strip().lower()
        subs = [s for s in subs if k in " ".join([s.team.name if s.team else "", s.sender_name, s.sender_email, s.subject]).lower()]
    if sort == "received_desc":
        subs.sort(key=lambda s: s.received_at, reverse=True)
    elif sort == "received_asc":
        subs.sort(key=lambda s: s.received_at)
    else:
        subs.sort(key=views.default_rank)
    start = (page - 1) * size
    return {"items": [views.list_item(s) for s in subs[start:start + size]], "total": len(subs), "page": page, "size": size}

