"""파이썬 문서 리더(minutes_review.extract) 감싸기: 형식 판별, 회의록 판별, 칸 안 그림(서명·영수증) 확인.

Upstage 추출값의 `has_signature`·`receipt_attached`는 자주 틀려서, 칸 안에 그림이 있는지 직접 본다.
스캔본(글자 층 없는 PDF)은 칸 정보가 없으므로 signature.py가 OCR 좌표로 따로 본다.
"""
from __future__ import annotations

import re

from minutes_review.extract import UnsupportedFormat, load, sniff
from minutes_review.model import Document


def classify(data: bytes, filename: str) -> tuple[str, Document | None]:
    """→ (format, Document|None). format: hwp hwpx docx pdf scan image unknown"""
    fmt = sniff(data, filename)
    if fmt == "unknown":
        return "unknown", None
    try:
        doc = load(data, filename)
    except (UnsupportedFormat, Exception):
        # PDF 글자 층을 못 읽어도 쪽 그림은 그릴 수 있다 → 스캔본처럼 OCR로 읽는다
        return ("scan", None) if fmt == "pdf" else (fmt, None)
    if fmt == "pdf" and (not any(p.text.strip() for p in doc.pages) or garbled(doc)):
        return "scan", doc
    return fmt, doc


def garbled(doc: Document) -> bool:
    """PDF 글자 층이 깨졌는가. 한글에서 PDF로 저장한 파일은 글꼴 정보 때문에 글자를 뽑으면 엉뚱한 문자가 나오는 일이 많다.
    글자는 꽤 있는데 한글이 거의 없으면 깨진 것으로 보고 스캔본처럼 OCR로 읽는다."""
    text = re.sub(r"\s+", "", "".join(p.text for p in doc.pages))
    if len(text) < 30:
        return False
    hangul = len(re.findall(r"[가-힣]", text))
    return hangul / len(text) < 0.15


_FORM_TITLE = re.compile(
    r"(?:\[별첨[^\]]+\]\.?)?(?:동아리|캡스톤(?:디자인)?|WE-?Meet)?"
    r"회의비(?:지출)?증빙(?:자료|양식)?", re.I)


def is_minutes(doc: Document | None, fmt: str) -> bool:
    """사업단 회의비 지출 증빙 양식인가: 빈 양식 파일에서 뽑은 칸 이름과 대조해 60% 이상 맞으면 (form_check).
    스캔본은 글자 층이 없어 OCR 전에는 알 수 없으므로 일단 후보로 본다."""
    if fmt == "scan":
        return True
    from .form_check import check_document

    if doc is None or check_document(doc).status not in ("match", "partial"):
        return False
    # 안내문에도 양식명과 칸 이름이 인용된다. 독립된 제목 또는 실제 칸 구조를 확인한다.
    cells = {re.sub(r"\s+", "", c.flat) for p in doc.pages for t in p.tables for row in t.rows for c in row}
    lines = cells | {re.sub(r"\s+", "", line) for p in doc.pages for line in p.body_lines}
    if any(_FORM_TITLE.fullmatch(line) for line in lines):
        return True
    from .form_check import spec

    labels = {re.sub(r"\s+", "", label) for label in spec().labels}
    found = labels & cells
    core = {"회의명", "회의일시", "회의장소", "회의내용"} & found
    return len(core) >= 3 and len(found) >= 8


def screen(files: list[tuple[str, bytes]]) -> str | None:
    """접수 전 거르기. 첨부가 있는데 회의비 증빙 양식이 하나도 없으면 버린다(사업단 보안 우려: 증빙이 아닌 서류를 보관하지 않음).
    → 버릴 이유 문자열, 받으면 None. 첨부가 없는 메일은 받는다('미첨부' 보완 요청 대상).
    사진·스캔본·판독 실패는 양식 미확인으로 보존하고 후속 검수로 보낸다.
    버릴 때는 이유에 첨부마다 형식·크기·양식 칸 일치율을 남긴다(파일 이름·내용은 남기지 않음)."""
    return screen_result(files)[1]


def screen_result(files: list[tuple[str, bytes]]) -> tuple[str, str | None]:
    """form / not_form / unverified / no_attachment. 판독 실패를 비대상으로 단정하지 않는다."""
    if not files:
        return "no_attachment", None
    from .form_check import check_document

    seen, unverified = [], False
    for name, data in files:
        ext = name.rsplit(".", 1)[-1].lower()[:6] if "." in name else "?"
        fmt, doc = classify(data, name)
        if fmt in ("scan", "image"):
            unverified = True
            continue
        if doc is None:
            if data.lstrip().startswith((b"BEGIN:VCALENDAR", b"[InternetShortcut]")):
                seen.append(f"{ext}→일정·바로가기 (문서 아님)")
                continue
            seen.append(f"{ext}→{fmt} 읽기 실패 {len(data) // 1024}KB")
            unverified = True
            continue
        r = check_document(doc)
        if is_minutes(doc, fmt):
            return "form", None
        seen.append(f"{ext}→{fmt} 칸 {r.ratio:.0%} {len(data) // 1024}KB")
    if unverified:
        return "unverified", None
    return "not_form", "회의비 증빙 양식이 아닌 첨부만 있음 (" + "; ".join(seen) + ")"


FORM_FIELDS = {"팀명": "team_name", "회의명": "meeting_title", "회의장소": "place", "사용비용": "used_amount"}


def form_fields(doc: Document | None) -> dict:
    """디지털 양식에서 칸 값을 직접 읽는다(라벨 칸 바로 다음 칸). Upstage 추출이 옆 칸 글까지 붙여 읽는 경우가 있어
    (예: 회의장소에 회의내용 일부가 붙음, 2026-10-31 실제 PDF) 팀명·회의명·장소·사용 비용은 이 값을 우선한다."""
    out: dict = {}
    if doc is None:
        return out
    for p in doc.pages:
        for t in p.tables:
            for r in t.rows:
                texts = [c.flat for c in r]
                for i, tx in enumerate(texts[:-1]):
                    key = FORM_FIELDS.get(re.sub(r"\s+", "", tx))
                    if key and key not in out and texts[i + 1]:
                        out[key] = texts[i + 1]
    if "used_amount" in out:
        digits = re.sub(r"[^0-9]", "", out["used_amount"])
        out["used_amount"] = int(digits) if digits else None
    return out


def full_text(doc: Document | None) -> str:
    return "\n".join(p.text for p in doc.pages) if doc else ""


def receipt_image(doc: Document | None) -> bytes | None:
    """영수증 라벨 바로 아래 칸의 그림만 반환한다. 서명·로고는 재추출하지 않는다."""
    if doc is None:
        return None
    for page in doc.pages:
        for table in page.tables:
            for i, row in enumerate(table.rows[:-1]):
                label = [re.sub(r"\s+", "", c.flat) for c in row]
                if len(label) == 1 and label[0].endswith("영수증") and len(label[0]) <= 8:  # '영수증', '식사 영수증' 등
                    for cell in table.rows[i + 1]:
                        for image in cell.images:
                            if image.data:
                                return image.data
    return None


def _sig(cell):
    """서명 칸: 그림이 있으면 True, 그림 없이 글자만 있으면 "typed"(워드 작성 서명), 비어 있으면 False."""
    if cell.images:
        return True
    return "typed" if cell.flat else False


def local_marks(doc: Document) -> dict:
    """칸 안 그림 확인: 참석자별 서명, 결제자 서명, 영수증 칸 그림. (run_cases.py local_marks 이식)"""
    out = {"attendee_signed": {}, "payer_signed": None, "receipt_image": None, "attendee_page": None, "receipt_page": None}
    for p in doc.pages:
        for t in p.tables:
            rows = t.rows
            for i, r in enumerate(rows):
                texts = [c.flat for c in r]
                if "이름" in texts and "서명" in texts and "학번" in texts:  # 참석자 머리 행
                    out["attendee_page"] = p.no
                    width = len(texts) - texts.index(next(x for x in texts if x in ("소속", "학번")))  # 소속·학번·이름·서명
                    name_at = texts.index("이름") - texts.index("서명") - 1  # 서명 칸 기준 이름 칸 위치(보통 -2)
                    pending: list = []
                    for r2 in rows[i + 1:]:
                        # 학생이 칸을 나누거나 합쳐 서명 칸이 다음 줄로 떨어진 경우(이름 줄 3칸 + 서명 줄 1칸)도 한 사람으로 모은다
                        # (2026-11-02 EPOCH: 학번을 이름으로, 이름 글자를 워드 서명으로 오판)
                        if not pending and len(r2) < 3:
                            break
                        pending += r2
                        if len(pending) < width:
                            continue
                        person, pending = pending[:width], []
                        name = person[name_at].flat
                        if name:
                            out["attendee_signed"][name] = _sig(person[-1])
                if texts and texts[0] == "결제자" and i + 1 < len(rows):
                    out["payer_signed"] = _sig(rows[i + 1][-1])
                if texts == ["영수증"] and i + 1 < len(rows):
                    out["receipt_image"] = bool(rows[i + 1][0].images)
                    out["receipt_page"] = p.no
    return out
