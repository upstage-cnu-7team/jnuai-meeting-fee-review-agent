"""S3 팀 상세·별칭, S4 기준 보기."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import views
from ..db import get_db
from ..errors import ApiError
from ..models import PROGRAMS, RuleSet, Submission, Team, User, iso
from ..review.conditions import source_text
from ..schemas import AliasesPut, ErrorResponse, RuleSetOut, TeamDetail
from ..security import current_user, require_program
from ..views import PROGRAM_NAMES

router = APIRouter(tags=["teams", "rules"])
ERR = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}


def _team(db: Session, user: User, team_id: str) -> Team:
    t = db.get(Team, team_id)
    if t is None:
        raise ApiError(404, "TEAM_NOT_FOUND", "팀을 찾을 수 없습니다.")
    require_program(user, t.program)
    return t


def _team_out(db: Session, t: Team) -> dict:
    subs = db.scalars(select(Submission).where(Submission.team_id == t.id).order_by(Submission.received_at.desc()))
    items = []
    for s in subs:
        sm = views.list_summary(s) or {}
        items.append({"id": s.id, "received_at": iso(s.received_at), "meeting_date": sm.get("meeting_date"), "total_amount": sm.get("total_amount"),
                      "verdict": s.verdict if s.processing_status == "done" else None, "reply_status": views.reply_status(s)})
    return {"id": t.id, "program": t.program, "name": t.name, "aliases": t.aliases or [], "known_senders": t.known_senders or [], "submissions": items}


@router.get("/teams/{team_id}", response_model=TeamDetail, responses=ERR, tags=["teams"])
def team_detail(team_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return _team_out(db, _team(db, user, team_id))


@router.put("/teams/{team_id}/aliases", response_model=TeamDetail, responses=ERR, tags=["teams"])
def put_aliases(team_id: str, body: AliasesPut, db: Session = Depends(get_db), user: User = Depends(current_user)):
    t = _team(db, user, team_id)
    t.aliases = list(dict.fromkeys(a.strip() for a in body.aliases if a.strip()))
    db.commit()
    return _team_out(db, t)


@router.get("/programs/{program}/rules", response_model=RuleSetOut, responses=ERR, tags=["rules"])
def rules(program: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if program not in PROGRAMS:
        raise ApiError(404, "PROGRAM_NOT_FOUND", "프로그램을 찾을 수 없습니다.")
    require_program(user, program)
    q = select(RuleSet).where(RuleSet.status == "confirmed").order_by(RuleSet.version.desc())
    rs = db.scalars(q.where(RuleSet.program == program)).first()
    note = None
    if rs is None:
        rs = db.scalars(q.where(RuleSet.program == "club")).first()
        if rs is None:
            raise ApiError(404, "RULE_SET_NOT_FOUND", "확정된 기준이 없습니다.")
        note = f"{PROGRAM_NAMES[program]} 확정 기준이 아직 없어 동아리 기준으로 임시 판정합니다."
    conds = [{"id": c["id"], "name": c["name"], "by": c["by"], "severity": c["severity"], "params": c.get("params") or {},
              "source": source_text(c.get("source")), "enabled": c.get("enabled", True)} for c in rs.conditions]
    conds += [{"id": r["id"], "name": r["name"], "enabled": False, "excluded_reason": r.get("excluded_reason")} for r in rs.removed or []]
    return {"id": rs.id, "program": rs.program, "version": rs.version, "status": rs.status, "confirmed_by": rs.confirmed_by,
            "confirmed_at": iso(rs.confirmed_at), "conditions": conds, "note": note}
