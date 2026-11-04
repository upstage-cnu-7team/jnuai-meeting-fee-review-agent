"""수집 메일(Power Automate가 보내는 '[수집] 원래 제목') 해석과 접수. 웹훅·Gmail 가져오기·.eml 가져오기가 같은 함수를 쓴다.

수집 메일 본문 맨 위 (docs/devlog/2026-10-29-mail-domain.md 10/30):
    FROM: 원래 보낸 학생          TO: 원래 받은 담당자 주소(→ 담당자 메일함·프로그램 후보)
    CC: …   RECEIVED: 원래 받은 시각   INTERNET_MSGID: 원본 Message-ID(중복 방지)   MSGID: 종희 메일함 ID
    ATTACHMENTS: 개수   MATCHED: 필터에 맞은 팀 키
    (빈 줄) 원문 본문
접수 규칙: INTAKE_SINCE 이전 메일·회의비 증빙 양식이 아닌 첨부만 있는 메일은 받지 않고, 원본 Message-ID로 중복을 막는다.
"""
from __future__ import annotations

import email
import email.policy
import base64
import binascii
import logging
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime

from pydantic import BaseModel
from sqlalchemy import select

from ..config import get_settings
from ..models import KST, Submission
from ..review import readers
from . import links
from minutes_review.extract import sniff

log = logging.getLogger("intake")

META_KEYS = ["FROM", "TO", "CC", "RECEIVED", "INTERNET_MSGID", "MSGID", "ATTACHMENTS", "MATCHED"]
_META = re.compile(r"^\s*(" + "|".join(META_KEYS) + r"|보낸 사람|받는 사람|받은 시간|메시지 ID)\s*[:：]\s*(.*)$")
_ALIAS = {"보낸 사람": "FROM", "받는 사람": "TO", "받은 시간": "RECEIVED", "메시지 ID": "MSGID"}


HELD_PREFIX = "양식 검토 대기: "


class IntakeResult(BaseModel):
    id: str | None = None
    duplicate: bool = False
    skipped: str | None = None  # 받지 않은 이유 (기간 밖, 양식 아님)


def _split_meta(text: str) -> tuple[dict, str]:
    """본문 앞쪽 메타 줄을 떼어 낸다 → (메타, 원문 본문)."""
    meta, rest, started = {}, [], False
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        m = _META.match(ln)
        if m:
            meta[_ALIAS.get(m[1], m[1])] = m[2].strip()
            started = True
            continue
        if started and not ln.strip() and not meta.get("_end"):
            meta["_end"] = i
            continue
        rest.append(ln)
    meta.pop("_end", None)
    return meta, "\n".join(rest).strip()


def mailbox_of(to_line: str, subject: str) -> str | None:
    """원래 받은 담당자 주소 → 메일함. MANAGER_MAILBOXES(.env)에 'club_manager=주소,wemeet_manager=주소'로 둔다."""
    table = {}
    for pair in (get_settings().manager_mailboxes or "").split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            table[v.strip().lower()] = k.strip()
    for addr in re.findall(r"[\w.+-]+@[\w.-]+", to_line or ""):
        if addr.lower() in table:
            return table[addr.lower()]
    t = f"{to_line} {subject}"
    if re.search(r"\[수집:위밋\]|위밋|wemeet", t, re.I):
        return "wemeet_manager"
    if "동아리" in t:
        return "club_manager"
    return None


def _when(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00")) if re.match(r"\d{4}-", v) else parsedate_to_datetime(v)
    except (TypeError, ValueError):
        return None
    return dt.astimezone(KST).replace(tzinfo=None) if dt.tzinfo else dt


def parse_mail(raw: bytes) -> dict:
    """메일 원본 → 접수 정보. 수집 메일이면 본문 메타의 원래 보낸 사람·받은 시각·원본 Message-ID를 쓴다."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain", "html"))
    text = body.get_content() if body else ""
    if body is not None and body.get_content_type() == "text/html":
        text = re.sub(r"<br\s*/?>|</p>|</div>", "\n", text, flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text).replace("&nbsp;", " ")
    meta, original = _split_meta(text)
    subject = re.sub(r"^\s*\[수집(:[^\]]*)?\]\s*", "", str(msg["subject"] or ""))
    sender_name, sender_email = parseaddr(meta.get("FROM") or str(msg["from"] or ""))
    files = []
    for part in msg.iter_attachments():
        data = part.get_payload(decode=True) or b""
        if data:
            name = part.get_filename() or "첨부"
            # 일부 Power Automate 전달분은 MIME 디코딩 뒤에도 Base64 문자열이다.
            # 이미 정상인 문서는 그대로 두고, 검증 가능한 파일 헤더가 나올 때만 한 겹 복구한다.
            if sniff(data, name) == "unknown":
                try:
                    decoded = base64.b64decode(re.sub(rb"\s+", b"", data), validate=True)
                    if (sniff(decoded, name) != "unknown" or decoded.startswith(b"BEGIN:VCALENDAR")
                            or decoded.startswith(b"[InternetShortcut]")):
                        data = decoded
                except (binascii.Error, ValueError):
                    pass
            files.append((name, data))
    msgid = meta.get("INTERNET_MSGID") or meta.get("MSGID") or str(msg["message-id"] or "") or None
    return {"subject": subject, "body_text": original, "sender_name": sender_name, "sender_email": sender_email.lower(),
            "received_at": _when(meta.get("RECEIVED")) or _when(msg["date"]), "message_id": msgid,
            "mailbox": mailbox_of(meta.get("TO") or "", str(msg["subject"] or "")), "files": files}


def intake_raw(db, raw: bytes) -> IntakeResult:
    """메일 원본(MIME, 제목·본문·첨부 포함)을 임시 저장한 뒤 판별한다.

    접수·중복·비대상 처리가 확정되면 임시본을 삭제한다. 처리 예외 시에는
    원본을 잃지 않도록 임시본을 남긴다. 메일 내용은 로그에 쓰지 않는다.
    """
    pending = get_settings().data_dir / "intake_pending"
    pending.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, path = tempfile.mkstemp(prefix="intake_", suffix=".eml", dir=pending)
    staged = Path(path)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    review_path = None
    if get_settings().intake_review_mode:
        review_dir = get_settings().data_dir / "intake_review"
        review_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        review_path = review_dir / f"{hashlib.sha256(raw).hexdigest()}.eml"
        review_path.write_bytes(raw)
        review_path.chmod(0o600)
    try:
        result = _intake_staged(db, staged.read_bytes())
    except Exception:
        log.warning("intake pending: %s (처리 실패, 원본 보존)", staged.name)
        raise
    if review_path:
        outcome = review_path.with_suffix(".json")
        outcome.write_text(json.dumps(result.model_dump(), ensure_ascii=False), encoding="utf-8")
        outcome.chmod(0o600)
    staged.unlink()
    return result


def _intake_staged(db, raw: bytes) -> IntakeResult:
    from .. import worker

    m = parse_mail(raw)
    since = get_settings().intake_since
    if since and m["received_at"] and m["received_at"] < since:
        return IntakeResult(skipped=f"접수 시작 시각({since:%m/%d %H:%M}) 이전 메일")
    decision, why = readers.screen_result(m["files"])
    hold = why
    text = f"{m['subject']}\n{m['body_text']}"
    if not hold and decision != "form" and "멘토링" in text:
        # 멘토링 일정 공유 메일(METRO·NoBrains)은 회의비 증빙이 아니다 → 양식 첨부가 없으면 검수하지 않고 보관 (2026-11-02 종희)
        hold = "멘토링 메일 (회의비 양식 첨부 없음)"
    if not hold and decision == "no_attachment" and not re.search(r"회의|증빙|영수증", text) and not links.find_links(m["body_text"]):
        # 첨부 없고 회의비 관련 단어도 없는 메일은 검수하지 않고 보관만 (2026-11-02 종희)
        hold = "첨부 없고 제목·본문에 회의비 관련 단어(회의·증빙·영수증) 없음"
    if not hold and decision in ("no_attachment", "unverified") and not _mentions_team(db, m):
        # 양식 첨부가 없고 제목·본문·파일명 어디에도 팀명이 없으면 이 서비스 메일이 아닐 가능성이 크다 (중계 계정 개인 메일·일정 초대 등)
        hold = "회의비 양식 첨부도 팀명도 없는 메일"
    if decision == "unverified" and not hold:
        log.info("intake unverified: 판독 실패·스캔 후보, 검수로 전달 (첨부 %d개)", len(m["files"]))
    if m["message_id"]:
        dup = db.scalar(select(Submission).where(Submission.mail_message_id == m["message_id"]))
        if dup:
            return IntakeResult(id=dup.id, duplicate=True)
    sub = worker.create_submission(db, **m)
    save_raw(sub.id, raw)
    if hold:
        # 버리지 않고 '양식 검토 대기'로 남긴다. 담당자(종희)가 목록을 보고 확인한 뒤 지운다 (2026-11-02 종희)
        # 목록·삭제: tools/held_mail.py
        log.info("intake held: %s (첨부 %d개)", hold, len(m["files"]))
        sub.processing_status, sub.processing_error = "failed", f"{HELD_PREFIX}{hold}"
        db.commit()
        return IntakeResult(id=sub.id, skipped=hold)
    worker.enqueue(sub.id)
    return IntakeResult(id=sub.id)


def _mentions_team(db, m: dict) -> bool:
    from ..models import Team
    from ..review.team_match import TeamCandidate, match_team
    from . import links

    if links.find_links(m["body_text"]):
        return True
    text = "\n".join([m["subject"], m["body_text"], *(n for n, _ in m["files"])])
    teams = [TeamCandidate(t.id, t.name, t.aliases or [], t.strict, t.members or []) for t in db.scalars(select(Team))] if db else []
    return not teams or match_team(teams, None, text)[0] is not None  # 팀 목록이 없으면 거르지 않는다


def save_raw(submission_id: str, raw: bytes):
    """받은 메일 원본(.eml)을 data/raw/에 둔다. 접수한 메일만 저장한다(양식 아닌 메일·기간 밖 메일은 남기지 않음)."""
    d = get_settings().data_dir / "raw"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{submission_id}.eml").write_bytes(raw)
