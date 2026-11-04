"""필드 추출: 회의비 지출 증빙(회의록) + 영수증 첨부철 + 영수증에서 판정에 쓸 값을 뽑는다.

규칙 기반(라벨 칸 → 옆 칸, '라벨: 값' 줄)을 먼저 쓰고, 일시·장소 칸처럼 형식이 제각각이라 규칙으로
못 푼 칸만 LLM 보조(assist)에 맡긴다. 모든 값에는 근거 위치(쪽·칸)와 원문을 붙인다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, time
from typing import Any, Callable

from .model import Cell, Document, Image, Page, Table, key, norm

# 체크 표시로 인정하는 문자 (□만 빈 칸). ·은 한글 Wingdings 계열 체크 상자
CHECKED = "■☑☒▣✔✓●◼√✅"
BOXES = "□" + CHECKED


@dataclass
class Field:
    value: Any = None
    page: int | None = None
    where: str = ""
    raw: str = ""

    def ev(self, label: str | None = None) -> dict:
        """판정 근거 한 줄 (JSON용)."""
        return {"page": self.page, "where": self.where, "value": norm(self.raw) if self.raw else None, **({"label": label} if label else {})}


@dataclass
class Attendee:
    name: str
    signed: bool
    page: int | None
    where: str


@dataclass
class Receipt:
    present: bool = False
    needs_ocr: bool = False
    page: int | None = None
    total: Field = field(default_factory=Field)
    date: Field = field(default_factory=Field)
    time: Field = field(default_factory=Field)
    merchant: Field = field(default_factory=Field)
    address: Field = field(default_factory=Field)
    method: Field = field(default_factory=Field)  # 'card' / 'cash' / None
    card_number: Field = field(default_factory=Field)
    lines: list[str] = field(default_factory=list)


@dataclass
class Fields:
    minutes_page: int | None = None
    attach_page: int | None = None
    round: Field = field(default_factory=Field)
    club_type: Field = field(default_factory=Field)  # value: 체크된 항목 목록
    attach_club_type: Field = field(default_factory=Field)
    club_field: Field = field(default_factory=Field)
    club_name: Field = field(default_factory=Field)
    attach_club_name: Field = field(default_factory=Field)
    meeting_date: Field = field(default_factory=Field)
    start: Field = field(default_factory=Field)
    end: Field = field(default_factory=Field)
    place: Field = field(default_factory=Field)
    topic: Field = field(default_factory=Field)
    content: Field = field(default_factory=Field)
    attendees: list[Attendee] = field(default_factory=list)
    attendees_where: Field = field(default_factory=Field)
    photos: list[Image] = field(default_factory=list)
    photo_field: Field = field(default_factory=Field)
    loose_images_on_minutes: int = 0
    attach_date: Field = field(default_factory=Field)
    attach_amount: Field = field(default_factory=Field)
    receipt: Receipt = field(default_factory=Receipt)
    assisted: list[str] = field(default_factory=list)  # LLM 보조로 채운 필드 이름
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def v(f: Field):
            x = f.value
            if isinstance(x, (date, time)):
                return x.isoformat(timespec="minutes") if isinstance(x, time) else x.isoformat()
            return x

        r = self.receipt
        return {
            "회의록_쪽": self.minutes_page,
            "첨부철_쪽": self.attach_page,
            "회의_차수": v(self.round),
            "동아리_구분": v(self.club_type),
            "첨부철_동아리_구분": v(self.attach_club_type),
            "동아리_분야": v(self.club_field),
            "동아리명": v(self.club_name),
            "첨부철_동아리명": v(self.attach_club_name),
            "회의일": v(self.meeting_date),
            "시작": v(self.start),
            "종료": v(self.end),
            "장소": v(self.place),
            "주제": v(self.topic),
            "회의내용": v(self.content),
            "참석자": [{"성명": a.name, "서명": a.signed} for a in self.attendees],
            "사진_수": len(self.photos),
            "첨부철_날짜": v(self.attach_date),
            "첨부철_금액": v(self.attach_amount),
            "영수증": {
                "있음": r.present,
                "OCR_필요": r.needs_ocr,
                "쪽": r.page,
                "금액": v(r.total),
                "거래일": v(r.date),
                "결제_시각": v(r.time),
                "가맹점": v(r.merchant),
                "주소": v(r.address),
                "결제수단": v(r.method),
                "카드번호": v(r.card_number),
            },
            "LLM_보조_필드": self.assisted,
            "메모": self.notes,
        }


# ───────────────────────────── 값 해석 ─────────────────────────────
_DATE = re.compile(r"(20\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})\s*[.일]?")
_TIME = re.compile(r"(오전|오후|AM|PM|am|pm)?\s*(\d{1,2})\s*(?::\s*(\d{2})(?:\s*:\s*\d{2})?|시\s*(?:(\d{1,2})\s*분|반)?)")
_AMOUNT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원?")
_CARDNO = re.compile(r"(?<![\d*])[\d*]{4}[-\s][\d*]{2,4}[-\s]?[\d*]{0,4}[-\s][\d*]{3,4}(?![\d*])")
_WEEKDAY = re.compile(r"\(\s*[월화수목금토일]\s*(?:요일)?\s*\)")


def parse_date(text: str) -> tuple[date | None, re.Match | None]:
    m = _DATE.search(text or "")
    if not m:
        return None, None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])), m
    except ValueError:  # 양식 기본값 2026.00.00. 등
        return None, m


def parse_times(text: str) -> list[tuple[time, re.Match]]:
    out = []
    last_ampm = ""
    for m in _TIME.finditer(text or ""):
        h = int(m[2])
        mi = int(m[3] or m[4] or (30 if m[0].rstrip().endswith("반") else 0))
        ampm = (m[1] or "").lower() or last_ampm  # '오후 5시~6시'의 6시도 오후
        last_ampm = ampm
        if ampm in ("오후", "pm") and h < 12:
            h += 12
        if ampm in ("오전", "am") and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            out.append((time(h, mi), m))
    return out


def parse_amount(text: str) -> int | None:
    best = None
    for m in _AMOUNT.finditer(text or ""):
        n = int(m[1].replace(",", ""))
        if n > 0 and (best is None or n > best):
            best = n
    return best


def checked_options(text: str) -> list[str]:
    """'■ SW전공 □ SW창업' → ['SW전공']."""
    t = re.sub(r"\(.*?작성.*?\)", "", text or "")
    out = []
    for m in re.finditer(rf"([{BOXES}])\s*([^{BOXES}\n]+)", t):
        if m[1] != "□":
            out.append(norm(m[2]))
    return out


# ───────────────────────────── 표 탐색 ─────────────────────────────
def _find_table(doc: Document, label_keys: set[str]) -> tuple[Page, Table] | tuple[None, None]:
    for p in doc.pages:
        for t in p.tables:
            firsts = {key(r[0].text) for r in t.rows if r}
            if label_keys <= firsts:
                return p, t
    return None, None


def _row(t: Table, label: str) -> list[Cell] | None:
    for r in t.rows:
        if r and key(r[0].text) == key(label):
            return r
    return None


def _after(row: list[Cell], label: str) -> Cell | None:
    for i, c in enumerate(row[:-1]):
        if key(c.text) == key(label):
            return row[i + 1]
    return None


# ───────────────────────────── 추출 ─────────────────────────────
Assist = Callable[[str], dict | None]  # 일시·장소 칸 원문 → {"date","start","end","place"} (LLM 보조)


def extract_fields(doc: Document, guide_phrases: list[str] = (), assist: Assist | None = None) -> Fields:
    f = Fields()
    mp, mt = _find_table(doc, {"동아리명", "회의주제"})
    if mt is None:
        mp, mt = _find_table(doc, {"회의주제"})
    if mt is not None:
        _minutes(f, mp, mt, assist)
    else:
        f.notes.append("회의비 지출 증빙(회의록) 표를 찾지 못함")
    ap, at = _find_attach(doc)
    if at is not None:
        _attach(f, ap, at)
    else:
        f.notes.append("영수증 첨부철 표(날짜·금액)를 찾지 못함")
    _receipt(f, doc, mt, at)
    return f


def _find_attach(doc: Document):
    cands = []
    for p in doc.pages:
        for t in p.tables:
            r = _row(t, "날짜")
            if r and any(key(c.text) == "금액" for c in r):
                cands.append((("영수증첨부철" in key(p.text)), p, t))
    if not cands:
        return None, None
    cands.sort(key=lambda x: not x[0])
    return cands[0][1], cands[0][2]


def _minutes(f: Fields, p: Page, t: Table, assist: Assist | None) -> None:
    f.minutes_page = p.no
    T = "회의비 지출 증빙"

    m = re.search(r"\(\s*(\d+)\s*\)\s*차", p.text)
    f.round = Field(int(m[1]) if m else None, p.no, f"{T} 제목 '( )차'", m[0] if m else "")

    r = _row(t, "동아리구분")
    if r and len(r) > 1:
        f.club_type = Field(checked_options(r[1].text), p.no, f"{T} '동아리 구분' 칸", r[1].text)
    r = _row(t, "동아리분야")
    if r and len(r) > 1:
        f.club_field = Field(checked_options(r[1].text), p.no, f"{T} '동아리 분야' 칸", r[1].text)
    r = _row(t, "동아리명")
    if r and len(r) > 1:
        f.club_name = Field(r[1].flat or None, p.no, f"{T} '동아리명' 칸", r[1].flat)

    # 일시 및 장소 (한 칸) 또는 일시·장소 (두 칸)
    r = _row(t, "일시및장소")
    if r and len(r) > 1:
        _datetime_place(f, r[1].text, p.no, f"{T} '일시 및 장소' 칸", assist)
    else:
        r1, r2 = _row(t, "일시"), _row(t, "장소")
        if r1 and len(r1) > 1:
            _datetime_place(f, r1[1].text, p.no, f"{T} '일시' 칸", assist, place=False)
        if r2 and len(r2) > 1:
            f.place = Field(r2[1].flat or None, p.no, f"{T} '장소' 칸", r2[1].flat)

    r = _row(t, "회의주제")
    if r and len(r) > 1:
        f.topic = Field(r[1].flat or None, p.no, f"{T} '회의 주제' 칸", r[1].flat)
    r = _row(t, "회의내용")
    if r and len(r) > 1:
        f.content = Field(r[1].flat or None, p.no, f"{T} '회의내용' 칸", r[1].flat)

    _attendees(f, p, t)

    r = _row(t, "회의사진")
    if r:
        f.photos = [img for c in r[1:] for img in c.images]
        f.photo_field = Field(len(f.photos), p.no, f"{T} '회의 사진' 칸", f"그림 {len(f.photos)}개")
    f.loose_images_on_minutes = len(p.loose_images)


def _attendees(f: Fields, p: Page, t: Table) -> None:
    rows, inside = [], False
    for r in t.rows:
        k = key(r[0].text) if r else ""
        if k == "참석자":
            inside = True
            rows.append(r[1:])
            continue
        if inside:
            if k in ("일시및장소", "일시", "회의주제", "장소"):
                break
            rows.append(r)
    where = "회의비 지출 증빙 '참석자' 칸"
    f.attendees_where = Field(None, p.no, where, "")
    for cells in rows:
        if len(cells) == 1:  # 명단을 한 칸에 몰아 쓴 경우: 서명은 판단 불가
            for name in re.split(r"[,、/\n]", cells[0].text):
                name = norm(re.sub(r"성명|\(서명\)", "", name))
                if name:
                    f.attendees.append(Attendee(name, False, p.no, where))
            f.notes.append("참석자 명단이 한 칸에 적혀 있어 서명 여부를 칸별로 확인할 수 없음")
            continue
        for i in range(0, len(cells) - 1, 2):
            name_cell, sig_cell = cells[i], cells[i + 1]
            name = norm(re.sub(r"^성\s*명\s*[:：]?", "", name_cell.flat))
            sig_text = norm(re.sub(r"\(\s*서\s*명\s*\)", "", sig_cell.flat))
            signed = bool(sig_cell.images or name_cell.images or sig_text)
            if name:
                f.attendees.append(Attendee(name, signed, p.no, where))
            elif signed:
                f.notes.append("이름 없이 서명만 있는 참석자 칸이 있음")


def _datetime_place(f: Fields, text: str, page: int, where: str, assist: Assist | None, place: bool = True) -> None:
    flat = norm(text)
    d, dm = parse_date(flat)
    rest = flat[dm.end() :] if dm else flat
    times = parse_times(rest)
    f.meeting_date = Field(d, page, where, flat)
    if times:
        f.start = Field(times[0][0], page, where, flat)
    if len(times) > 1:
        f.end = Field(times[1][0], page, where, flat)
    if place:
        left = flat
        for m in [dm] + [m for _t, m in times]:
            if m is not None:
                left = left.replace(m[0], " ", 1)
        left = _WEEKDAY.sub(" ", left)
        left = re.sub(r"(일시|장소)\s*[:：]", " ", left)
        left = norm(re.sub(r"^[\s~\-–/|,·:]+|[\s~\-–/|,·:]+$", "", re.sub(r"\s*[~\-–]\s*(?=[/|,]|$)", "", left)))
        left = norm(re.sub(r"^[/|,]\s*|\s*[/|,]$", "", left))
        f.place = Field(left or None, page, where, flat)
    if assist and flat and (d is None or len(times) < 2 or (place and not f.place.value)):
        got = assist(flat) or {}
        _apply_assist(f, got, page, where, flat, place)


def _apply_assist(f: Fields, got: dict, page: int, where: str, flat: str, place: bool) -> None:
    """LLM 답을 그대로 믿지 않는다: 원문에 실제로 있는 숫자·글자로만 채운다."""
    digits = re.sub(r"\D", "", flat)
    if f.meeting_date.value is None and got.get("date"):
        try:
            d = date.fromisoformat(got["date"])
            if f"{d.month}" in digits and f"{d.day}" in digits:
                f.meeting_date = Field(d, page, where + " (AI 보조)", flat)
                f.assisted.append("회의일")
        except ValueError:
            pass
    for name, attr in (("start", "start"), ("end", "end")):
        if getattr(f, attr).value is None and got.get(name):
            try:
                tm = time.fromisoformat(got[name])
                if str(tm.hour % 12 or 12) in digits or str(tm.hour) in digits:
                    setattr(f, attr, Field(tm, page, where + " (AI 보조)", flat))
                    f.assisted.append("시작" if name == "start" else "종료")
            except ValueError:
                pass
    if place and not f.place.value and got.get("place") and norm(got["place"]) in flat:
        f.place = Field(norm(got["place"]), page, where + " (AI 보조)", flat)
        f.assisted.append("장소")


def _attach(f: Fields, p: Page, t: Table) -> None:
    f.attach_page = p.no
    T = "영수증 첨부철"
    r = _row(t, "동아리구분")
    if r and len(r) > 1:
        f.attach_club_type = Field(checked_options(r[1].text), p.no, f"{T} '동아리 구분' 칸", r[1].text)
    r = _row(t, "동아리명")
    if r and len(r) > 1:
        f.attach_club_name = Field(r[1].flat or None, p.no, f"{T} '동아리명' 칸", r[1].flat)
    r = _row(t, "날짜")
    c = _after(r, "날짜") if r else None
    if c is not None:
        f.attach_date = Field(parse_date(c.flat)[0], p.no, f"{T} '날짜' 칸", c.flat)
    c = _after(r, "금액") if r else None
    if c is not None:
        f.attach_amount = Field(parse_amount(c.flat), p.no, f"{T} '금액' 칸", c.flat)


# ───────────────────────────── 영수증 ─────────────────────────────
_RECEIPT_LABELS = {
    "total": r"(?:승인\s*금액|결제\s*금액|합\s*계(?:\s*금액)?|총\s*액|총\s*금액|받을\s*금액|청구\s*금액)",
    "datetime": r"(?:거래\s*일시|승인\s*일시|결제\s*일시|거래\s*일자|매출\s*일시)",
    "merchant": r"(?:가맹점\s*명|가맹점|상\s*호(?:\s*명)?)",
    "address": r"(?:가맹점\s*주소|사업장\s*주소|주\s*소)",
    "method": r"(?:결제\s*수단|결제\s*방법|지불\s*수단|거래\s*유형|거래\s*종류)",
    "card": r"(?:카드\s*번호)",
}
_TOTAL_PRIORITY = ["승인금액", "결제금액", "합계금액", "합계", "총금액", "총액", "받을금액", "청구금액"]


def _label_value(line: str, pattern: str) -> tuple[str, str] | None:
    m = re.match(rf"^\s*\[?({pattern})\]?\s*[:：]?\s*(.*)$", line)
    if not m:
        return None
    return key(m[1]), m[2].strip()


def _receipt(f: Fields, doc: Document, minutes_t: Table | None, attach_t: Table | None) -> None:
    """영수증 블록 = 회의록·첨부철 라벨 칸을 뺀 나머지 텍스트에서 영수증 라벨이 있는 줄들."""
    R = f.receipt
    lines: list[tuple[int, str, str]] = []  # (쪽, 줄, 위치 설명)
    for p in doc.pages:
        if p.no == f.minutes_page:
            continue  # 회의록 쪽 본문의 '영수증 날짜' 안내문 등은 영수증이 아님
        for ln in p.body_lines:
            lines.append((p.no, ln, f"{p.no}쪽 영수증"))
        for t in p.tables:
            if t is minutes_t:
                continue
            for r in t.rows:
                if t is attach_t and r and key(r[0].text) in ("동아리구분", "동아리분야", "동아리명", "날짜"):
                    continue
                for c in r:
                    for ln in c.text.splitlines():
                        lines.append((p.no, ln, f"{p.no}쪽 영수증"))

    found: dict[str, tuple[int, str, str, str]] = {}  # 이름 → (쪽, 라벨, 값, 원문)
    totals: list[tuple[int, int, str, str]] = []
    block: list[str] = []
    for pg, ln, _w in lines:
        for name, pat in _RECEIPT_LABELS.items():
            lv = _label_value(ln, pat)
            if lv is None:
                continue
            if name == "address" and found.get("merchant") and lv[0] == "주소" and "주소" in found:
                continue
            if name == "total":
                amt = parse_amount(lv[1])
                if amt:
                    rank = _TOTAL_PRIORITY.index(lv[0]) if lv[0] in _TOTAL_PRIORITY else len(_TOTAL_PRIORITY)
                    totals.append((rank, amt, ln, str(pg)))
                    block.append(ln)
                break
            if name == "merchant" and lv[0].startswith("가맹점") and lv[0] != "가맹점명" and lv[0] != "가맹점":
                continue
            found.setdefault(name, (pg, lv[0], lv[1], ln))
            block.append(ln)
            break
        else:
            if _CARDNO.search(ln) and "card" not in found:
                found["card"] = (pg, "카드번호", _CARDNO.search(ln)[0], ln)
                block.append(ln)
            elif re.search(r"매출\s*전표|영\s*수\s*증|현금\s*영수증|신용\s*승인", ln) and "첨부철" not in ln:
                block.append(ln)
    R.lines = block
    R.present = bool(totals or "datetime" in found or "merchant" in found)
    if R.present:
        pages = [pg for pg, *_ in found.values()] + [int(t[3]) for t in totals]
        R.page = min(pages) if pages else None
    W = lambda pg: f"{pg}쪽 영수증"  # noqa: E731

    if totals:
        totals.sort(key=lambda x: x[0])
        rank, amt, ln, pg = totals[0]
        R.total = Field(amt, int(pg), W(pg) + " 금액", ln)
    if "datetime" in found:
        pg, _l, val, ln = found["datetime"]
        d, dm = parse_date(val)
        R.date = Field(d, pg, W(pg) + " 거래일시", ln)
        ts = parse_times(val[dm.end() :] if dm else val)
        if ts:
            R.time = Field(ts[0][0], pg, W(pg) + " 거래일시", ln)
    if "merchant" in found:
        pg, _l, val, ln = found["merchant"]
        R.merchant = Field(val or None, pg, W(pg) + " 가맹점명", ln)
    if "address" in found:
        pg, _l, val, ln = found["address"]
        R.address = Field(val or None, pg, W(pg) + " 주소", ln)
    if "card" in found:
        pg, _l, val, ln = found["card"]
        m = _CARDNO.search(val) or _CARDNO.search(ln)
        R.card_number = Field(m[0] if m else None, pg, W(pg) + " 카드번호", ln)
    if "method" in found:
        pg, _l, val, ln = found["method"]
        R.method = Field(_method(val), pg, W(pg) + " 결제수단", ln)
    elif R.present:
        text = " ".join(block)
        R.method = Field(_method(text), R.page, (W(R.page) if R.page else "영수증") + " 전체", text[:120])
    if R.method.value is None and R.card_number.value:
        R.method = Field("card", R.card_number.page, R.card_number.where, R.card_number.raw)

    if not R.present:
        # 영수증 글자가 없는데 첨부철 쪽·별도 이미지에 그림이 있으면 사진 영수증으로 본다 (OCR 범위 밖)
        attach = next((p for p in doc.pages if p.no == f.attach_page), None)
        imgs = (attach.image_count if attach else 0) + sum(p.image_count for p in doc.pages if not p.text.strip())
        if imgs or doc.kind == "image" or doc.needs_ocr:
            R.needs_ocr = True
            R.page = f.attach_page


_CARD_WORDS_DEFAULT = ["신용카드", "체크카드", "카드"]
_CASH_WORDS_DEFAULT = ["현금", "계좌이체", "이체", "무통장"]


def _method(text: str, card_words=None, cash_words=None) -> str | None:
    card = any(w in text for w in (card_words or _CARD_WORDS_DEFAULT))
    cash = any(w in text for w in (cash_words or _CASH_WORDS_DEFAULT))
    if card and not cash:
        return "card"
    if cash and not card:
        return "cash"
    return None
