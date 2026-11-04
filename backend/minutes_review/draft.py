"""보완 요청 초안: 미충족·확인필요 항목으로 학생에게 보낼 회신 본문을 만든다.

담당자가 화면에서 고친 뒤 [전송]하는 초안이다. 확인필요 항목은 담당자가 직접 확인할 것이라 학생 본문에는 넣지 않고
담당자 메모로 따로 돌려준다 (확인 전 학생에게 허위 지적을 보내지 않기 위함).
"""
from __future__ import annotations

from .checks import CHECK, UNMET, Check


def _where(c: Check) -> str:
    parts = []
    for e in c.evidence:
        if e.get("where"):
            loc = e["where"] if str(e["where"]).startswith(f"{e.get('page')}쪽") or e.get("page") is None else f"{e['page']}쪽 {e['where']}"
            parts.append(loc)
    return ", ".join(dict.fromkeys(parts))


def make_draft(checks: list[Check], verdict: str, club: str | None = None, round_no: int | None = None) -> dict:
    unmet = [c for c in checks if c.result == UNMET]
    unsure = [c for c in checks if c.result == CHECK]
    title_round = f" {round_no}차" if round_no else ""
    subject = f"[SW중심대학사업단] {club or '동아리'}{title_round} 회의비 증빙 " + ("검수 결과 안내" if verdict == "적합" else "보완 요청")

    lines = [f"{club or '동아리'} 담당 학생께,", "", f"제출하신{title_round} 회의비 지출 증빙 서류를 검토했습니다."]
    if not unmet:
        lines += ["서류에 보완할 사항이 없습니다. 감사합니다." if not unsure else "현재 학생이 보완할 사항은 없으며, 일부 항목은 담당자가 확인 중입니다."]
    else:
        bad = [c for c in unmet if c.severity == "부적합"]
        fix = [c for c in unmet if c.severity != "부적합"]
        if bad:
            lines += ["", "■ 회의비 인정 기준에 맞지 않는 항목"]
            for i, c in enumerate(bad, 1):
                lines += [f"{i}. {c.name}", f"   - 확인 내용: {c.detail}" + (f" ({_where(c)})" if _where(c) else ""),
                          f"   - 기준: {c.basis}", f"   - 안내: {c.action}"]
        if fix:
            lines += ["", "■ 보완해 주실 항목"]
            for i, c in enumerate(fix, 1):
                lines += [f"{i}. {c.name}", f"   - 확인 내용: {c.detail}" + (f" ({_where(c)})" if _where(c) else ""),
                          f"   - 기준: {c.basis}", f"   - 요청: {c.action}"]
        lines += ["", "위 내용을 반영해 이 메일에 회신으로 다시 제출해 주세요." if fix else "위 사항에 대해 소명할 내용이 있으면 회신해 주세요."]
    lines += ["", "전남대학교 SW중심대학사업단 드림"]

    memo = [f"[{c.id}] {c.name}: {c.detail} — {c.action}" for c in unsure]
    return {"subject": subject, "body": "\n".join(lines), "staff_memo": memo, "send_needed": bool(unmet)}
