"""검수 대기열: 제출 접수 → (백그라운드) LangGraph 검수 → DB 저장.

처음엔 프로세스 안 스레드 2개로 돈다. 서버가 재시작되면 queued·processing 건을 다시 넣는다.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlalchemy import func, select

from .config import get_settings
from .db import session
from .graph.review_graph import GRAPH
from .mail import links
from .models import Check, File, Reply, RuleSet, Submission, Team, now_kst
from .review import upstage
from .review.pages import png_size
from .review.pipeline import MODEL_INFO
from .review.team_match import TeamCandidate
from .storage import read_original, save_original, save_pages

log = logging.getLogger("review")
_pool = ThreadPoolExecutor(2, thread_name_prefix="review")


def new_submission_id(db, when: datetime) -> str:
    prefix = f"s_{when:%Y%m%d}_"
    n = db.scalar(select(func.count(Submission.id)).where(Submission.id.like(prefix + "%"))) or 0
    return f"{prefix}{n + 1:04d}"


def create_submission(db, *, files: list[tuple[str, bytes]], mailbox: str | None, sender_name: str, sender_email: str, subject: str,
                      body_text: str, received_at: datetime | None = None, message_id: str | None = None, program: str | None = None) -> Submission:
    received_at = received_at or now_kst()
    sub = Submission(id=new_submission_id(db, received_at), mailbox=mailbox, program=program, sender_name=sender_name, sender_email=sender_email,
                     subject=subject, body_text=body_text, received_at=received_at, mail_message_id=message_id)
    for i, (name, data) in enumerate(files):
        sub.files.append(File(order=i, name=name, size=len(data), sha256=save_original(data)))
    sub.reply = Reply(status="none", to_email=sender_email)
    db.add(sub)
    db.commit()
    return sub


def rule_sets_for(db) -> dict[str, dict]:
    """프로그램별 최신 확정 기준. 확정 기준이 없는 프로그램은 동아리 기준을 임시로 쓴다(위밋 지침 미수령)."""
    out = {}
    for rs in db.scalars(select(RuleSet).where(RuleSet.status == "confirmed").order_by(RuleSet.version)):
        out[rs.program] = {"id": rs.id, "conditions": rs.conditions, "removed": rs.removed}
    for p in ("club", "aim", "hackathon", "wemeet", "capstone"):
        if p not in out and "club" in out:
            out[p] = {**out["club"], "fallback_from": "동아리"}
    return out


def enqueue(submission_id: str):
    if get_settings().run_review_inline:
        run_review(submission_id)
    else:
        _pool.submit(run_review, submission_id)


def fetch_link_files(db, sub: Submission) -> list[str]:
    """본문의 대용량 첨부 링크(네이버 등)에서 파일을 받아 첨부로 더한다. 실패는 담당자 메모로 돌려준다."""
    if not links.find_links(sub.body_text or ""):
        return []
    got, notes = links.fetch_all(sub.body_text or "", {f.name for f in sub.files})
    for name, data in got:
        sub.files.append(File(order=len(sub.files), name=name, size=len(data), sha256=save_original(data)))
    if got:
        db.commit()
    return notes


def run_review(submission_id: str, cache: upstage.Cache | None = None):
    cache = cache or upstage.Cache()
    with session() as db:
        sub = db.get(Submission, submission_id)
        if sub is None:
            return
        sub.processing_status, sub.processing_error = "processing", None
        db.commit()
        link_notes = fetch_link_files(db, sub)
        teams = {}
        for t in db.scalars(select(Team)):
            teams.setdefault(t.program, []).append(TeamCandidate(t.id, t.name, t.aliases or [], t.strict, t.members or []))
        state = {"files": [{"file_id": f.id, "name": f.name, "data": read_original(f.sha256)} for f in sub.files],
                 "mailbox": sub.mailbox, "program": sub.program, "subject": sub.subject, "body_text": sub.body_text,
                 "received_at": sub.received_at, "teams_by_program": teams, "rule_sets": rule_sets_for(db),
                 "fixed_team_id": sub.team_id if sub.team_match == "manual" else None, "cache": cache,
                 "intake_notes": link_notes}
        try:
            out = GRAPH.invoke(state)
        except Exception as e:  # 원문이 섞일 수 있어 예외 종류와 짧은 설명만 남긴다
            log.warning("review failed %s: %s", submission_id, type(e).__name__)
            sub.processing_status = "failed"
            sub.processing_error = str(e)[:200] if isinstance(e, upstage.UpstageError) else f"검수 중 오류가 발생했습니다 ({type(e).__name__})"
            db.commit()
            return
        save_result(db, sub, out)


def save_result(db, sub: Submission, out: dict):
    by_id = {f.id: f for f in sub.files}
    for fi in out["file_info"]:
        f = by_id[fi["file_id"]]
        f.kind, f.format = fi["kind"], fi["format"]
        save_pages(f.id, fi["pages"])
        f.pages = [{"n": i, "width": png_size(p)[0], "height": png_size(p)[1]} for i, p in enumerate(fi["pages"], 1)]
        f.page_count = len(fi["pages"])
    sub.program = out.get("program")
    if sub.team_match != "manual":
        sub.team_id = out.get("team_id")
        sub.team_match = "auto" if sub.team_id else "none"
        sub.team_match_reason = out.get("team_reason")
    sub.rule_set_id = out.get("rule_set_id")
    sub.extracted = out.get("extracted")
    sub.verdict = out["verdict"]
    sub.model_info = {**MODEL_INFO, "program_reason": out.get("program_reason"), "reviewed_at": now_kst().isoformat()}
    sub.checks.clear()
    db.flush()
    for c in out["checks"]:
        sub.checks.append(Check(check_id=c["check_id"], name=c["name"], by=c["by"], severity=c["severity"], result=c["result"],
                                ai_result=c["ai_result"], overridden=False, message=c["message"], evidence=c["evidence"]))
    r = sub.reply or Reply(to_email=sub.sender_email)
    sub.reply = r
    if r.status in ("none", "draft", "failed") and not r.edited_by_manager:
        rep = out["reply"]
        r.subject, r.body, r.internal_notes, r.status = rep["subject"], rep["body"], rep["internal_notes"], "draft"
    else:
        r.internal_notes = out["reply"]["internal_notes"]
    sub.processing_status = "done"
    sub.updated_at = now_kst()
    db.commit()


def requeue_unfinished():
    with session() as db:
        ids = list(db.scalars(select(Submission.id).where(Submission.processing_status.in_(["queued", "processing"]))))
    for i in ids:
        enqueue(i)
