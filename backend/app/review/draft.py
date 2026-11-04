"""회신 초안: 학생 본문에는 미충족(unmet)만, 확인필요(review)는 담당자 메모(internal_notes)로만.

확인 전 학생에게 허위 지적을 보내지 않기 위해서다. 담당자가 화면에서 고친 뒤 직접 보낸다.
"""
from __future__ import annotations

import re

from .conditions import REVIEW, UNMET

# 학생에게 보내지 않을 내부 메모: '(추출의 첨부 여부 값은 …)', '(추출값과 다름: …)' 같은 판정 근거 꼬리
_INTERNAL = re.compile(r"\s*\((추출|AI|판정)[^)]*\)")


def _student_text(msg: str) -> str:
    return _INTERNAL.sub("", msg).strip()

SIGNATURE = "인공지능혁신융합대학사업단 드림"


def make_reply(checks: list[dict], subject: str, team_name: str | None = None) -> dict:
    unmet = [c for c in checks if c["result"] == UNMET]
    unsure = [c for c in checks if c["result"] == REVIEW]
    reply_subject = subject if subject.upper().startswith("RE:") else f"RE: {subject}".strip()
    who = f"{team_name} 팀" if team_name else "학생"
    lines = ["안녕하세요, 인공지능혁신융합대학사업단입니다.", f"{who}에서 제출해 주신 회의비 증빙을 확인했습니다."]
    if len(unmet) == 1 and unmet[0]["evidence"].get("field") == "attachments" and unmet[0]["evidence"].get("found") == "첨부 0개":
        # 첨부가 아예 없는 메일: 항목 목록 대신 바로 안내 (2026-11-02)
        lines = ["안녕하세요, 인공지능혁신융합대학사업단입니다.", "",
                 f"{team_name + ' 팀에서 ' if team_name else ''}보내 주신 회의비 증빙 메일에 첨부파일이 첨부되지 않았습니다.",
                 "회의비 지출 증빙 양식(회의록, 영수증 사진 포함) 파일을 첨부하여 다시 보내 주세요."]
    elif not unmet:
        lines += ["", "확인 결과 보완할 사항이 없습니다. 감사합니다."]
    else:
        bad = [c for c in unmet if c["severity"] == "reject"]
        fix = [c for c in unmet if c["severity"] != "reject"]
        n = 0
        if bad:
            lines += ["", "■ 회의비 인정 기준에 맞지 않는 항목"]
            for c in bad:
                n += 1
                lines += [f"{n}. {c['name']}: {_student_text(c['message'])}"]
        if fix:
            lines += ["", "■ 보완해 주실 항목"]
            for c in fix:
                n += 1
                lines += [f"{n}. {c['name']}: {_student_text(c['message'])}"]
        lines += ["", "위 내용을 반영해 다시 제출해 주세요." if fix else "위 사항에 대해 소명할 내용이 있으면 회신해 주세요."]
    lines += ["", SIGNATURE]
    notes = [f"{c['check_id']} {c['name']}: {c['message']}" for c in unsure]
    return {"subject": reply_subject, "body": "\n".join(lines), "internal_notes": notes, "send_needed": bool(unmet)}
