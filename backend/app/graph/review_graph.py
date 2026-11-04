"""LangGraph 검수 흐름. 노드는 app/review 함수를 부르기만 하고, 판정 로직은 넣지 않는다.

START → load_files → extract ─┬─ scan ────▶ ocr_signature ─┐
                              └─ digital ─▶ read_local ────┴▶ judge_solar → match_team → judge_code → draft → END
                 (회의록 없음) ─▶ no_minutes → draft → END

한 메일에 회의록이 여러 개면 각 노드가 회의록마다 따로 돌고, judge_code가 회의록별 판정을 한 목록으로 모은다
(항목 이름 앞에 '[10/27 회의록]', check_id 뒤에 '-1'·'-2'). 팀·프로그램은 첫 회의록으로 정한다 (2026-11-03 종희, VCCC·EPOCH).

담당자 확인 대기는 그래프 밖(DB review_status)에서 관리한다. 그래프는 초안까지 만들고 끝난다.
Upstage 재시도(3회)는 upstage.py 안에서 한다.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ..review import form_check, pages, pipeline, readers, slim, team_match, upstage
from ..review.conditions import EXCLUDED, REVIEW, UNMET
from ..review.draft import make_reply
from ..review.verdict import verdict


class FileIn(TypedDict):
    file_id: str
    name: str
    data: bytes


class ReviewState(TypedDict, total=False):
    # 입력
    files: list[FileIn]
    mailbox: str | None
    program: str | None  # 담당자가 이미 정했으면 그대로
    subject: str
    body_text: str
    received_at: datetime
    teams_by_program: dict[str, list[team_match.TeamCandidate]]
    rule_sets: dict[str, dict]  # program → {"id", "conditions", "removed", "fallback_from"}
    fixed_team_id: str | None  # 담당자가 지정한 팀
    cache: Any
    # 중간·결과
    file_info: list[dict]  # {file_id, kind, format, pages:[png...]}
    minutes: dict | None  # {file_id, name, data, format, doc} — 첫 회의록 (팀·프로그램 판별용)
    minutes_all: list[dict]  # 모든 회의록 (회의록마다 따로 판정)
    per_file: list[dict]  # 회의록별 {ie, marks, solar, form_text}, minutes_all과 같은 순서
    form_text: str  # 스캔본의 OCR 글자 (디지털 파일은 문서 리더 글자를 쓴다)
    ie: dict
    marks: dict
    solar: dict
    program_reason: str
    team_id: str | None
    team_reason: str
    rule_set_id: str | None
    checks: list[dict]
    verdict: str
    reply: dict
    extracted: dict | None
    notes: list[str]
    intake_notes: list[str]  # 접수 단계 메모 (대용량 링크 받기 실패 등)


def load_files(s: ReviewState) -> dict:
    info, all_minutes, notes = [], [], list(s.get("intake_notes") or [])
    for f in s["files"]:
        fmt, doc = readers.classify(f["data"], f["name"])
        kind = "other"
        if readers.is_minutes(doc, fmt):
            kind = "minutes"
            all_minutes.append({"file_id": f["file_id"], "name": f["name"], "data": f["data"], "format": fmt, "doc": doc})
        elif fmt == "image":
            kind = "receipt"
        view = slim.for_upstage(f["data"], f["name"]) if fmt in ("hwpx", "docx", "image") else f["data"]  # 큰 사진은 줄인 사본으로 그림 (HWP는 그릴 때 줄임)
        info.append({"file_id": f["file_id"], "kind": kind, "format": fmt, "pages": pages.render_pages(view, fmt, doc)})
    if not all_minutes and s["files"]:
        notes.append("첨부 중 회의록 양식을 찾지 못했습니다. 첨부 파일을 직접 확인해 주세요.")
    if len(all_minutes) > 1:
        notes.append(f"회의록이 {len(all_minutes)}개 첨부되어 회의록마다 따로 판정했습니다. 항목 이름 앞의 [날짜 회의록]으로 구분합니다.")
    return {"file_info": info, "minutes": all_minutes[0] if all_minutes else None, "minutes_all": all_minutes, "notes": notes}


def _all(s: ReviewState) -> list[dict]:
    return s.get("minutes_all") or ([s["minutes"]] if s.get("minutes") else [])


def route_after_load(s: ReviewState) -> str:
    return "extract" if s.get("minutes") else "no_minutes"


def extract(s: ReviewState) -> dict:
    per = [{"ie": pipeline.extract_all(m["data"], m["doc"], s["cache"], m["name"])} for m in _all(s)]
    return {"ie": per[0]["ie"], "per_file": per}


def route_format(s: ReviewState) -> str:
    return "ocr_signature" if s["minutes"]["format"] == "scan" else "read_local"


def _read_marks(s: ReviewState) -> dict:
    """회의록마다 자기 형식대로 서명·영수증 칸을 본다(같은 메일에 스캔본과 디지털 파일이 섞여도 됨)."""
    per = []
    for m, p in zip(_all(s), s["per_file"]):
        marks = pipeline.marks_for(m["format"], m["doc"], m["data"], m["name"], p["ie"], s["cache"])
        # 스캔본은 OCR 글자로 별첨 제목을 본다 (캐시 적중)
        form_text = upstage.ocr(m["data"], m["name"], s["cache"]).get("text", "") if m["format"] == "scan" else ""
        per.append({**p, "marks": marks, "form_text": form_text})
    return {"per_file": per, "marks": per[0]["marks"], "form_text": per[0]["form_text"]}


def ocr_signature(s: ReviewState) -> dict:
    return _read_marks(s)


def read_local(s: ReviewState) -> dict:
    return _read_marks(s)


def judge_solar(s: ReviewState) -> dict:
    per = [{**p, "solar": upstage.solar(p["ie"], s["cache"])} for p in s["per_file"]]
    return {"per_file": per, "solar": per[0]["solar"]}


def _mail_text(s: ReviewState) -> str:
    names = " ".join(f["name"] for f in s["files"])
    return f"{s.get('subject', '')}\n{s.get('body_text', '')}\n{names}"


def match_team(s: ReviewState) -> dict:
    m = s.get("minutes")
    form_text = (s.get("form_text") or readers.full_text(m["doc"])) if m else ""
    ie = s.get("ie") or {}
    attendees = [a.get("name") for a in ie.get("attendees") or [] if a.get("name")]
    d = team_match.decide(form_text, s.get("mailbox"), _mail_text(s), ie.get("team_name"), attendees, s["teams_by_program"])
    program, reason = (s["program"], "담당자 지정") if s.get("program") else (d.program, d.program_reason)
    if s.get("program") and s["program"] != d.program:  # 담당자가 정한 프로그램 안에서 팀을 다시 찾는다
        tid, tr = team_match.match_team(s["teams_by_program"].get(program, []), ie.get("team_name"), _mail_text(s))
        d = team_match.Decision(program, reason, tid, tr)
    notes = list(s.get("notes") or [])
    if d.alert and not s.get("fixed_team_id"):
        notes.insert(0, d.alert)
    if s.get("fixed_team_id"):
        return {"program": program, "program_reason": reason, "team_id": s["fixed_team_id"], "team_reason": "담당자 지정", "notes": notes}
    return {"program": program, "program_reason": reason, "team_id": d.team_id, "team_reason": d.team_reason if program else d.program_reason,
            "notes": notes}


def judge_code(s: ReviewState) -> dict:
    rs = s["rule_sets"].get(s.get("program") or "club") or s["rule_sets"]["club"]
    notes = list(s.get("notes") or [])
    if rs.get("fallback_from"):
        notes.append(f"이 프로그램의 확정 기준이 없어 {rs['fallback_from']} 기준으로 임시 판정했습니다.")
    files = _all(s)
    per = s.get("per_file") or [{"ie": s["ie"], "marks": s["marks"], "solar": s["solar"], "form_text": s.get("form_text")}]
    labels = _labels(files, per)
    checks = []
    for i, (m, p) in enumerate(zip(files, per), 1):
        one = pipeline.judge_file(p["ie"], p["solar"], p["marks"], s["received_at"], rs, m["file_id"])
        one.insert(0, pipeline.form_check_item(m["doc"], p.get("form_text") if m["format"] == "scan" else None, m["file_id"]))
        if len(files) > 1:  # 회의록마다 항목을 따로 둔다. 제외 조건은 한 번만 보인다
            one = [c for c in one if c["result"] != EXCLUDED] if i > 1 else one
            for c in one:
                if c["result"] != EXCLUDED:
                    c["check_id"], c["name"] = f"{c['check_id']}-{i}", f"[{labels[i - 1]}] {c['name']}"
        checks += one
    return {"checks": checks, "rule_set_id": rs["id"], "verdict": verdict(checks),
            "extracted": pipeline.extracted_view(per[0]["ie"], per[0]["marks"]), "notes": notes}


def _labels(files: list[dict], per: list[dict]) -> list[str]:
    """회의록 이름표: 회의 날짜('10/27 회의록'). 날짜가 없거나 겹치면 순번('회의록 2')."""
    out = []
    for i, p in enumerate(per, 1):
        d = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", str(p["ie"].get("meeting_date") or ""))
        out.append(f"{int(d[2])}/{int(d[3])} 회의록" if d else f"회의록 {i}")
    if len(set(out)) < len(out):
        out = [f"회의록 {i}" for i in range(1, len(per) + 1)]
    return out


def no_minutes(s: ReviewState) -> dict:
    out = match_team(s)
    rs = s["rule_sets"].get(out.get("program") or "club") or s["rule_sets"]["club"]
    r01 = next(c for c in rs["conditions"] if c["id"] == "R01")
    result, severity = UNMET, r01["severity"]
    if not s["files"] and s.get("intake_notes"):  # 대용량 링크를 받지 못함 → 학생 잘못이 아니다
        result, msg = REVIEW, "메일 본문의 대용량 첨부 링크에서 파일을 받지 못했습니다. 메일 원문에서 직접 확인해 주세요."
    elif not s["files"]:  # 첨부 자체가 없음 → 부적합 (2026-11-02 종희)
        severity, msg = "reject", NO_ATTACHMENT
    else:
        msg = "회의비 지출 증빙 양식의 회의록 파일을 찾지 못했습니다."
    check = {"check_id": "R01", "name": "증빙 첨부파일" if not s["files"] else r01["name"], "by": r01["by"], "severity": severity,
             "result": result, "ai_result": result, "overridden": False, "message": msg, "manager_note": None,
             "evidence": {"field": "attachments", "found": f"첨부 {len(s['files'])}개", "expected": "회의록 양식 파일", "file_id": None,
                          "page": None, "bbox": None, "rule_source": None}}
    return {**out, "checks": [check], "rule_set_id": rs["id"], "verdict": verdict([check]), "extracted": None}


NO_ATTACHMENT = "회의비 증빙 첨부파일 자체가 첨부되지 않았습니다. 회의비 지출 증빙 양식(회의록·영수증 사진 포함) 파일을 첨부해 다시 보내 주세요."


def draft(s: ReviewState) -> dict:
    team_name = (s.get("ie") or {}).get("team_name")
    if not team_name and s.get("team_id"):  # 첨부가 없으면 메일에서 찾은 팀 이름으로 부른다
        team_name = next((t.name for ts in s["teams_by_program"].values() for t in ts if t.id == s["team_id"]), None)
    reply = make_reply([c for c in s["checks"] if c["result"] != EXCLUDED], s.get("subject") or "회의비 증빙", team_name)
    reply["internal_notes"] = list(s.get("notes") or []) + reply["internal_notes"]
    return {"reply": reply}


def build_graph():
    g = StateGraph(ReviewState)
    for name, fn in [("load_files", load_files), ("extract", extract), ("ocr_signature", ocr_signature), ("read_local", read_local),
                     ("judge_solar", judge_solar), ("match_team", match_team), ("judge_code", judge_code), ("no_minutes", no_minutes),
                     ("draft", draft)]:
        g.add_node(name, fn)
    g.add_edge(START, "load_files")
    g.add_conditional_edges("load_files", route_after_load, ["extract", "no_minutes"])
    g.add_conditional_edges("extract", route_format, ["ocr_signature", "read_local"])
    g.add_edge("ocr_signature", "judge_solar")
    g.add_edge("read_local", "judge_solar")
    g.add_edge("judge_solar", "match_team")
    g.add_edge("match_team", "judge_code")
    g.add_edge("judge_code", "draft")
    g.add_edge("no_minutes", "draft")
    g.add_edge("draft", END)
    return g.compile()


GRAPH = build_graph()
