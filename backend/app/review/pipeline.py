"""검수 단계 함수. LangGraph 노드(app/graph)와 회귀 시험이 같은 함수를 부른다.

파일 하나(회의록) 기준:
  read → (scan이면 OCR 서명 / 아니면 칸 안 그림) → Information Extract → Solar → 조건 판정 → 종합 판정 → 회신 초안
"""
from __future__ import annotations

import re
from datetime import datetime

from minutes_review.model import Document

from . import conditions, draft, form_check, readers, signature, slim, upstage
from .verdict import verdict

MODEL_INFO = {"extract": "upstage information-extract", "ocr": "upstage document-digitization ocr", "judge": "upstage solar-pro4"}


RECEIPT_FIELDS = ["receipt_type", "merchant_name", "merchant_address", "card_type", "card_number", "approval_number",
                  "transaction_datetime", "receipt_items", "receipt_total", "receipt_discount", "receipt_paid"]


def receipt_missing(ie: dict) -> bool:
    return not conditions.paid_amount(ie)[0] or not (ie.get("merchant_name") or ie.get("transaction_datetime"))


def extract_all(data: bytes, doc: Document | None, cache: upstage.Cache, filename: str = "") -> dict:
    """회의록 전체를 추출하고, 영수증 값이 비었는데 영수증 사진이 있으면 그 사진만 다시 보내 영수증 값을 채운다.
    실제 영수증은 회의록 안에 붙인 휴대폰 사진이라 문서 전체 추출에서 놓칠 수 있다.
    큰 파일·큰 사진은 사진만 줄인 사본을 보낸다(slim, 큰 HWP는 PDF로). 판정용 doc은 원본에서 읽은 그대로다."""
    ie = upstage.extract(slim.for_extract(data, filename), cache)
    local = readers.form_fields(doc) if doc is not None and form_check.check_document(doc).status == "match" else {}
    changed = [k for k, v in local.items() if v not in (None, "") and str(ie.get(k) or "").replace(" ", "") != str(v).replace(" ", "")]
    if changed:  # 양식 칸에서 직접 읽은 값이 다르면 칸 값을 쓴다 (원래 추출값은 남겨 둔다)
        ie = {**ie, **{k: local[k] for k in changed}, "_extract_original": {k: ie.get(k) for k in changed}}
    if img := readers.receipt_image(doc):
        # 영수증 사진만 한 번 더 읽는다. 값이 비었을 때만이 아니라 늘: 작게 붙인 사진은 문서 전체 추출에서
        # 날짜·금액을 잘못 읽는다(AiBara 10-29 → 10-19, 80,000 → 77,945; 사진만 읽으면 맞음, 2026-11-04).
        # 사진에서 읽은 값이 있으면 그 값을 쓰고, 못 읽은 칸(사진이 2장이라 카드 전표가 빠진 경우 등)은 전체 추출 값을 둔다.
        try:
            again = upstage.extract(slim.shrink_image(img), cache)
        except upstage.UnreadableError:  # 사진에서 글자를 못 읽음 → R01 '영수증 인식 불가'로 확인필요
            return {**ie, "_receipt_retry": "unreadable"} if receipt_missing(ie) else ie
        if not receipt_missing(again):
            got = {k: again.get(k) for k in RECEIPT_FIELDS if again.get(k) not in (None, "", [], 0)}
            for k in ("merchant_name", "merchant_address"):  # 글자 칸은 더 길게(시 이름까지) 읽은 쪽을 둔다 ('북구 호들로' < '광주 북구 호동로 9-1')
                if k in got and len(str(ie.get(k) or "")) > len(str(got[k])):
                    del got[k]
            before = {k: ie.get(k) for k in got if k != "receipt_items" and ie.get(k) != got[k]}
            ie = {**ie, **got, "_receipt_retry": True, **({"_receipt_full_read": before} if before else {})}
    return ie


MINOR_LEFTOVER = {"작성자"}  # 예시 글이 남아도 보완필요로 두는 칸


def form_check_item(doc: Document | None, ocr_text: str | None, file_id: str | None) -> dict:
    """F00 양식 확인: 사업단 빈 양식(별첨 1-1)과 칸 대조. 지침 조건(R01~)과 별개로 맨 앞에 둔다.
    - 양식 일치 → 충족
    - 예시 글('회의 주제' 등)이 칸에 그대로 남음 → 부적합: 실제 회의에 맞게 채워야 함 (2026-10-31 종희 결정)
    - 칸 일부가 다름·글자를 못 읽음 → 확인필요"""
    r = form_check.check_document(doc, ocr_text)
    if r.status == "match" and not r.leftover:
        result, message = "met", r.message()
    elif r.leftover and r.status in ("match", "partial"):
        result, message = "unmet", r.student_message()
    else:
        result, message = "review", r.message()
    # 작성자 이름만 예시 글('작성자명')로 남았으면 보완필요 (2026-11-02 종희, NoBrains)
    minor = bool(r.leftover) and all(label in MINOR_LEFTOVER for label, _ in r.leftover)
    return {"check_id": "F00", "name": "사업단 회의비 지출 증빙 양식 (별첨 1-1)", "by": "code", "severity": "needs_fix" if minor else "reject",
            "result": result, "ai_result": result, "overridden": False, "message": message, "manager_note": None,
            "evidence": {"field": "form", "found": r.message(), "expected": "별첨 1-1 양식의 칸 13개를 실제 내용으로 채움", "file_id": file_id,
                         "page": 1, "bbox": None, "rule_source": "별첨1-1_회의비_지출증빙_양식.hwp", "alternatives": None}}


def marks_for(fmt: str, doc: Document | None, data: bytes, filename: str, ie: dict, cache: upstage.Cache) -> dict:
    """서명·영수증 칸 확인. 디지털 파일은 칸 안 그림, 스캔본은 OCR 좌표 + 잉크 비율."""
    if fmt == "scan":
        names = [a.get("name") for a in ie.get("attendees") or [] if a.get("name")]
        m = signature.signatures_from_scan(data, upstage.ocr(data, filename, cache), names, ie.get("payer_name"))
        m.pop("ink", None)
        return m
    if doc is None:
        return {"attendee_signed": {}, "payer_signed": None, "receipt_image": None}
    return readers.local_marks(doc)


def judge_file(ie: dict, sj: dict, marks: dict, submitted_at: datetime | None, rule_set: dict, file_id: str | None = None) -> list[dict]:
    checks = conditions.judge(ie, sj, marks, submitted_at, rule_set["conditions"], rule_set.get("removed") or [])
    for c in checks:  # 근거 위치: 서명은 참석자 표 쪽, 영수증 관련은 영수증 칸 쪽
        if c["result"] == conditions.EXCLUDED:
            continue
        c["evidence"]["file_id"] = file_id
        if c["check_id"] in ("R14",) and marks.get("attendee_page"):
            c["evidence"]["page"] = marks["attendee_page"]
        elif (c["evidence"]["field"] or "").startswith(("receipt", "merchant", "transaction", "approval", "card")) and marks.get("receipt_page"):
            c["evidence"]["page"] = marks["receipt_page"]
    return checks


def review_file(data: bytes, filename: str, submitted_at: datetime | None, rule_set: dict, cache: upstage.Cache,
                file_id: str | None = None) -> dict:
    """회의록 파일 하나를 끝까지 검수한다 (회귀 시험·단건 실행용)."""
    fmt, doc = readers.classify(data, filename)
    ie = extract_all(data, doc, cache, filename)
    marks = marks_for(fmt, doc, data, filename, ie, cache)
    sj = upstage.solar(ie, cache)
    checks = judge_file(ie, sj, marks, submitted_at, rule_set, file_id)
    ocr_text = upstage.ocr(data, filename, cache).get("text", "") if fmt == "scan" else None  # 스캔본은 OCR 글자로 양식 확인
    checks.insert(0, form_check_item(doc, ocr_text, file_id))
    return {"format": fmt, "ie": ie, "solar": sj, "marks": marks, "checks": checks, "verdict": verdict(checks)}


# ---- API 응답용 추출 요약 (frontend-api.md `extracted`) ----

def mask_student_id(s: str | None) -> str:
    s = (s or "").strip()
    return s[:4] + "*" * max(len(s) - 4, 0) if len(s) > 4 else s


def mask_card(s: str | None) -> str:
    """앞 4자리와 끝 4자리만 남긴다: 9410-****-****-1234"""
    digits = re.sub(r"\D", "", s or "")
    if not s:
        return ""
    groups = re.split(r"[-\s]", s.strip())
    if len(groups) >= 3:
        return "-".join([groups[0]] + ["****"] * (len(groups) - 2) + [groups[-1][-4:]])
    return digits[:4] + "*" * max(len(digits) - 8, 0) + digits[-4:] if len(digits) > 8 else "****"


def extracted_view(ie: dict, marks: dict) -> dict:
    sig = marks.get("attendee_signed") or {}
    payer_sig = marks.get("payer_signed")
    tx = ie.get("transaction_datetime") or ""
    tx_iso = None
    if m := re.match(r"(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})", tx):
        tx_iso = f"{m[1]}T{int(m[2]):02d}:{m[3]}:00+09:00"
    return {
        "team_name": ie.get("team_name"),
        "meeting_title": ie.get("meeting_title"),
        "meeting_date": ie.get("meeting_date"),
        "start_time": ie.get("start_time"),
        "end_time": ie.get("end_time"),
        "place": ie.get("place"),
        "content": ie.get("content"),
        "attendees": [{"affiliation": a.get("affiliation"), "student_id": mask_student_id(a.get("student_id")), "name": a.get("name"),
                       "has_signature": (sig[a.get("name")] is True) if a.get("name") in sig else bool(a.get("has_signature"))}
                      for a in ie.get("attendees") or []],
        "writer_name": ie.get("writer_name"),
        "used_amount": ie.get("used_amount"),
        "payer": {"affiliation": ie.get("payer_affiliation"), "name": ie.get("payer_name"),
                  "has_signature": (payer_sig is True) if payer_sig is not None else bool(ie.get("payer_has_signature"))},
        "receipt": {
            "attached": bool(conditions.paid_amount(ie)[0]) or marks.get("receipt_image") is True,
            "type": ie.get("receipt_type"),
            "merchant_name": ie.get("merchant_name"),
            "merchant_address": ie.get("merchant_address"),
            "card_type": ie.get("card_type"),
            "card_number": mask_card(ie.get("card_number")),
            "approval_number": ie.get("approval_number") or "",
            "transaction_datetime": tx_iso,
            "items": ie.get("receipt_items") or [],
            "total": conditions.paid_amount(ie)[0] or None,  # 할인 뒤 실제 결제금액
        },
    }


make_reply = draft.make_reply
