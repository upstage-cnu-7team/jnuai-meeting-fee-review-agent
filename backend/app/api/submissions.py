"""S2 제출 상세: 조회, 항목 수정, 초안 저장·재생성, 회신(잠정: 웹메일 + 보냈음 표시), 확인완료, 팀·프로그램 지정, 다시 검수."""
import re

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import views, worker
from ..db import get_db
from ..errors import ApiError
from ..models import Reply, Submission, Team, User, iso, now_kst
from ..review.draft import make_reply
from ..review.verdict import verdict as overall
from ..schemas import (CheckPatch, CheckPatchResponse, ConfirmRequest, ErrorResponse, QueuedResponse, ReplyOut, ReplyPut, SendResponse,
                       StatusResponse, SubmissionDetail, SubmissionPatch)
from ..security import current_user, require_program, require_submission

router = APIRouter(prefix="/submissions", tags=["submissions"])
ERR = {401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}
ERR409 = {**ERR, 409: {"model": ErrorResponse}}


def _get(db: Session, user: User, sid: str) -> Submission:
    return require_submission(user, db.get(Submission, sid))


def _reply(sub: Submission) -> Reply:
    if sub.reply is None:
        sub.reply = Reply(status="none", to_email=sub.sender_email)
    return sub.reply


def _locked(r: Reply):
    if r.status in ("sending", "sent"):
        raise ApiError(409, "REPLY_LOCKED", "이미 전송 중이거나 전송된 회신은 고칠 수 없습니다.")


def _check_dicts(sub: Submission) -> list[dict]:
    return [views.check_out(c) for c in sub.checks]


def _regenerate(sub: Submission):
    r = _reply(sub)
    team_name = sub.team.name if sub.team else (sub.extracted or {}).get("team_name")
    new = make_reply([c for c in _check_dicts(sub) if c["result"] != "excluded"], sub.subject or "회의비 증빙", team_name)
    keep = [n for n in (r.internal_notes or []) if not re.match(r"R\d\d ", n)]  # 항목 메모는 새로 만들고, 그래프가 넣은 안내는 남긴다
    r.subject, r.body, r.internal_notes = new["subject"], new["body"], keep + new["internal_notes"]
    r.edited_by_manager = False
    if r.status in ("none", "failed"):
        r.status = "draft"


@router.get("/{sid}", response_model=SubmissionDetail, responses=ERR)
def get_detail(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return views.detail(db, _get(db, user, sid))


@router.patch("/{sid}/checks/{check_id}", response_model=CheckPatchResponse, responses=ERR409,
              description="담당자가 항목 결과를 바꾼다. result=null이면 AI 결과로 되돌린다. excluded는 409")
def patch_check(sid: str, check_id: str, body: CheckPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    c = next((c for c in sub.checks if c.check_id == check_id), None)
    if c is None:
        raise ApiError(404, "CHECK_NOT_FOUND", "조건을 찾을 수 없습니다.")
    if c.ai_result == "excluded":
        raise ApiError(409, "CHECK_EXCLUDED", "이번 기준에서 제외된 조건은 바꿀 수 없습니다.")
    c.result = body.result or c.ai_result
    c.overridden = body.result is not None and body.result != c.ai_result
    if body.note is not None or body.result is None:
        c.manager_note = body.note
    sub.verdict = overall([d for d in _check_dicts(sub) if d["result"] != "excluded"])
    r = _reply(sub)
    regenerated = False
    if r.status not in ("sending", "sent") and not r.edited_by_manager:
        _regenerate(sub)
        regenerated = True
    sub.updated_at = now_kst()
    db.commit()
    return {"verdict": sub.verdict, "check": views.check_out(c), "reply": views.reply_out(sub), "reply_regenerated": regenerated,
            "updated_at": iso(sub.updated_at)}


@router.put("/{sid}/reply", response_model=ReplyOut, responses=ERR409)
def put_reply(sid: str, body: ReplyPut, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    r = _reply(sub)
    _locked(r)
    r.subject, r.body, r.edited_by_manager = body.subject, body.body, True
    if r.status in ("none", "failed", "not_needed"):
        r.status = "draft"
    sub.updated_at = now_kst()
    db.commit()
    return views.reply_out(sub)


@router.post("/{sid}/reply/regenerate", response_model=ReplyOut, responses=ERR409, description="현재 항목 결과로 초안을 다시 만든다(담당자 수정본을 덮어씀)")
def regenerate(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    _locked(_reply(sub))
    _regenerate(sub)
    sub.updated_at = now_kst()
    db.commit()
    return views.reply_out(sub)


@router.post("/{sid}/reply/mark-sent", response_model=StatusResponse, responses=ERR409,
             description="(잠정) 담당자가 웹메일로 직접 보낸 뒤 누른다. 서비스는 실제 발송 여부를 모른다")
def mark_sent(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    r = _reply(sub)
    if r.status == "sent":
        raise ApiError(409, "REPLY_LOCKED", "이미 보냄으로 표시된 회신입니다.")
    if not r.body.strip():
        raise ApiError(422, "REPLY_EMPTY", "회신 본문이 비어 있습니다.")
    r.status, r.sent_at, r.error = "sent", now_kst(), None
    sub.review_status = "confirmed"
    sub.updated_at = now_kst()
    db.commit()
    return {"review_status": sub.review_status, "reply_status": r.status}


@router.post("/{sid}/reply/send", status_code=202, response_model=SendResponse, responses={**ERR409, 422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
             description="(보류) 서비스 직접 발송. 담당자 동의 전까지 503 MAIL_BRIDGE_DOWN을 준다")
def send(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    r = _reply(sub)
    _locked(r)
    if not r.body.strip():
        raise ApiError(422, "REPLY_EMPTY", "회신 본문이 비어 있습니다.")
    raise ApiError(503, "MAIL_BRIDGE_DOWN", "서비스 직접 발송은 아직 열려 있지 않습니다. [웹메일에서 열기]로 보내고 [보냈음 표시]를 눌러 주세요.")


@router.post("/{sid}/confirm", response_model=StatusResponse, responses=ERR409, description="회신 없이 확인완료 (적합 등)")
def confirm(sid: str, body: ConfirmRequest | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    r = _reply(sub)
    sub.review_status = "confirmed"
    if r.status not in ("sending", "sent"):
        r.status = "not_needed"
    sub.updated_at = now_kst()
    db.commit()
    return {"review_status": sub.review_status, "reply_status": r.status}


@router.patch("/{sid}", response_model=SubmissionDetail, responses={**ERR, 422: {"model": ErrorResponse}},
              description="팀 지정·변경, 프로그램 미확정 건의 프로그램 지정, 확인완료 되돌리기. 마지막 저장이 이긴다")
def patch_submission(sid: str, body: SubmissionPatch, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    fields = body.model_fields_set
    if "program" in fields and body.program:
        require_program(user, body.program)
        if body.program != sub.program:
            sub.program = body.program
            if "team_id" not in fields:
                sub.team_id, sub.team_match, sub.team_match_reason = None, "none", "프로그램 변경"
    if "team_id" in fields:
        if body.team_id is None:
            sub.team_id, sub.team_match, sub.team_match_reason = None, "none", "담당자가 해제"
        else:
            team = db.get(Team, body.team_id)
            if team is None:
                raise ApiError(404, "TEAM_NOT_FOUND", "팀을 찾을 수 없습니다.")
            if sub.program is None:
                require_program(user, team.program)
                sub.program = team.program
            if team.program != sub.program:
                raise ApiError(422, "TEAM_PROGRAM_MISMATCH", "제출 건의 프로그램과 팀의 프로그램이 다릅니다.")
            sub.team_id, sub.team_match, sub.team_match_reason = team.id, "manual", "담당자 지정"
            if sub.sender_email and sub.sender_email not in (team.known_senders or []):
                team.known_senders = [*(team.known_senders or []), sub.sender_email]
    if "review_status" in fields and body.review_status == "pending":
        sub.review_status = "pending"  # 회신 상태는 바꾸지 않는다
    sub.updated_at = now_kst()
    db.commit()
    return views.detail(db, sub)


@router.post("/{sid}/rerun", status_code=202, response_model=QueuedResponse, responses=ERR, description="다시 검수 (실패했거나 기준이 바뀐 뒤)")
def rerun(sid: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    sub = _get(db, user, sid)
    sub.processing_status, sub.processing_error = "queued", None
    db.commit()
    worker.enqueue(sub.id)
    return JSONResponse({"processing_status": "queued"}, status_code=202)
