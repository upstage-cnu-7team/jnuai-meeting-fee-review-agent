"""DB 행 → API 응답 dict. 마스킹·서명 URL·정렬 규칙을 한곳에 둔다."""
from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import select

from .config import get_settings
from .models import Submission, iso
from .security import signed_url

PROGRAM_NAMES = {"club": "동아리", "aim": "AIM", "hackathon": "해커톤", "wemeet": "위밋", "capstone": "캡스톤"}
UNASSIGNED_TEAM = "팀 미확정"


def reply_status(sub: Submission) -> str:
    return sub.reply.status if sub.reply else "none"


def list_summary(sub: Submission) -> dict | None:
    if sub.processing_status != "done":
        return None
    ex = sub.extracted or {}
    unmet = [c.name for c in sub.checks if c.result == "unmet"]
    review = [c.name for c in sub.checks if c.result == "review"]
    total = (ex.get("receipt") or {}).get("total")
    return {"meeting_date": ex.get("meeting_date"), "total_amount": int(total) if total is not None else None,
            "attendee_count": len(ex.get("attendees") or []) if ex else None,
            "failed_checks": unmet, "review_checks": review, "failed_count": len(unmet), "review_count": len(review)}


def list_item(sub: Submission) -> dict:
    return {"id": sub.id, "program": sub.program, "team": {"id": sub.team_id, "name": sub.team.name if sub.team else UNASSIGNED_TEAM},
            "received_at": iso(sub.received_at), "sender": {"name": sub.sender_name, "email": sub.sender_email}, "subject": sub.subject,
            "processing_status": sub.processing_status, "verdict": sub.verdict if sub.processing_status == "done" else None,
            "review_status": sub.review_status, "reply_status": reply_status(sub), "summary": list_summary(sub)}


# 기본 정렬: 처리 실패 → 미확인(부적합 → 보완필요 → 확인필요 → 적합 → 검수 중·대기) → 확인완료, 그룹 안 최신순
_VERDICT_RANK = {"reject": 0, "needs_fix": 1, "review": 2, "pass": 3}


def default_rank(sub: Submission) -> tuple:
    if sub.processing_status == "failed":
        group = 0
    elif sub.review_status == "confirmed":
        group = 7
    elif sub.processing_status != "done":
        group = 6
    else:
        group = 1 + _VERDICT_RANK.get(sub.verdict, 3)
    return (group, -sub.received_at.timestamp())


def check_out(c) -> dict:
    return {"check_id": c.check_id, "name": c.name, "by": c.by, "severity": c.severity, "result": c.result, "ai_result": c.ai_result,
            "overridden": c.overridden, "message": c.message, "evidence": c.evidence or {}, "manager_note": c.manager_note}


_CHECK_ORDER = {"unmet": 0, "review": 1, "met": 2, "excluded": 3}


def compose(to: str, subject: str, body: str) -> tuple[str, bool]:
    """담당자 웹메일(OWA) 새 메일 창 주소. 주소 길이 제한 때문에 본문은 앞부분만 넣는다 (잠정, 학교 OWA 지원 여부 미시험)."""
    limit = get_settings().compose_max_chars
    truncated = len(body) > limit
    text = body[:limit] + ("\n…(이하 [초안 복사]로 붙여 넣기)" if truncated else "")
    url = f"{get_settings().owa_base}?path=/mail/action/compose&to={quote(to)}&subject={quote(subject)}&body={quote(text)}"
    return url, truncated


def reply_out(sub: Submission) -> dict:
    r = sub.reply
    if r is None:
        return {"status": "none", "to": sub.sender_email, "subject": "", "body": "", "internal_notes": [], "edited_by_manager": False,
                "sent_at": None, "error": None, "compose_url": None, "compose_truncated": False}
    url, trunc = compose(r.to_email, r.subject, r.body) if r.body else (None, False)
    return {"status": r.status, "to": r.to_email, "subject": r.subject, "body": r.body, "internal_notes": r.internal_notes or [],
            "edited_by_manager": r.edited_by_manager, "sent_at": iso(r.sent_at), "error": r.error, "compose_url": url, "compose_truncated": trunc}


def detail(db, sub: Submission) -> dict:
    atts = []
    for f in sub.files:
        atts.append({"file_id": f.id, "name": f.name, "kind": f.kind, "format": f.format, "page_count": f.page_count, "size": f.size,
                     "pages": [{**p, "url": signed_url(f"/api/files/{f.id}/pages/{p['n']}.png")} for p in f.pages or []],
                     "download_url": signed_url(f"/api/files/{f.id}/download")})
    prev = []
    if sub.team_id:
        q = select(Submission).where(Submission.team_id == sub.team_id, Submission.id != sub.id,
                                     Submission.received_at <= sub.received_at).order_by(Submission.received_at.desc()).limit(10)
        prev = [{"id": p.id, "received_at": iso(p.received_at), "verdict": p.verdict, "reply_status": reply_status(p)} for p in db.scalars(q)]
    rs = sub.rule_set
    return {
        "id": sub.id, "program": sub.program,
        "team": {"id": sub.team_id, "name": sub.team.name if sub.team else UNASSIGNED_TEAM, "match": sub.team_match,
                 "match_reason": sub.team_match_reason},
        "received_at": iso(sub.received_at), "sender": {"name": sub.sender_name, "email": sub.sender_email},
        "mail": {"subject": sub.subject, "body_text": sub.body_text}, "attachments": atts,
        "processing_status": sub.processing_status, "processing_error": sub.processing_error,
        "verdict": sub.verdict if sub.processing_status == "done" else None, "review_status": sub.review_status,
        "reply_status": reply_status(sub), "updated_at": iso(sub.updated_at),
        "rule_set": {"id": rs.id, "version": rs.version, "confirmed_at": iso(rs.confirmed_at)} if rs else None,
        "extracted": sub.extracted,
        "checks": [check_out(c) for c in sorted(sub.checks, key=lambda c: (_CHECK_ORDER.get(c.result, 9), c.check_id))],
        "reply": reply_out(sub), "previous_submissions": prev,
    }
