"""회의비 증빙(회의비 지출 증빙 + 영수증 첨부철 + 영수증) 가상 샘플을 HWP·HWPX·PDF·DOCX로 같은 내용으로 만든다.

    python tools/minutes_samples.py [출력 폴더]      # 기본: samples/minutes

모든 이름·동아리·가맹점·카드번호는 가상 데이터다. 사진·서명은 코드로 그린 그림이다.
양식 구성은 실제 '2. SW취업동아리 지출 증빙서류' HWP의 회의비 증빙(붙임6)·영수증 첨부철 표를 따른다.
"""
from __future__ import annotations

import copy
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.hwpkit import GCell, GTable, write_hwp, write_hwpx  # noqa: E402

GUIDE = ("※ 안내사항 숙지 후, 해당 내용은 지우고 회의내용 기록 ※\n▶ 회의일시와 회의비 영수증 날짜가 동일해야 함\n"
         "- 1일 1회, 1인당 2만원에 한하여 지원\n▶ 회의장소: 음식점, 카페X (ex. 강의실, 동아리실, 회의실 등)")

BASE = {
    "round": 3,
    "club_type": "SW전공",
    "club_field": "SW개발",
    "club_name": "코드메이트",
    "attendees": [("김가온", True), ("이나래", True), ("박다솜", True), ("최라온", True)],
    "datetime_place": "2026. 10. 14.(화) 17:00~18:30 / 공과대학 7호관 세미나실",
    "topic": "웹 서비스 MVP 기능 범위 확정",
    "content": ("1. 지난주 사용자 인터뷰 결과 공유: 일정 공유 기능 요구가 가장 많았음\n"
                "2. MVP 범위를 일정 등록·공유·알림 3개 기능으로 확정하고 담당자 배정(프론트 2명, 백엔드 2명)\n"
                "3. 결과: 10월 28일까지 화면 설계, 11월 4일까지 API 초안 완성하기로 결정"),
    "photos": 1,
    "attach_date": "2026.10.14.",
    "attach_amount": "64,000",
    "receipt": {
        "title": "[신용카드 매출전표]",
        "merchant": "가온마트 용봉점",
        "biz": "000-00-00000",
        "address": "광주광역시 북구 용봉로 0",
        "datetime": "2026-10-14 18:42:10",
        "card": "가상카드 5310-12**-****-3456",
        "method": "신용카드",
        "approval": "00000000",
        "total": "64,000원",
    },
}


def _case(name, expect, note, **change):
    c = copy.deepcopy(BASE)
    for k, v in change.items():
        if k.startswith("r_"):
            if v is None:
                c["receipt"].pop(k[2:], None)
            else:
                c["receipt"][k[2:]] = v
        else:
            c[k] = v
    c.update(name=name, expect=expect, note=note)
    return c


# expect: {항목: 결과} — 오프라인 규칙 기준 기대값. verdict는 오프라인 최종 판정
CASES = [
    _case("M01_정상", {"verdict": "확인필요", "unmet": []}, "모든 기준 충족 (사진 속 인원은 오프라인에선 확인필요, AI 판독 시 적합)"),
    _case("M02_날짜불일치", {"verdict": "부적합", "unmet": ["C5", "C14"]}, "회의일 10.14, 영수증 10.15 (다음 날 결제라 C14도 미충족)",
          r_datetime="2026-10-15 18:42:10", attach_date="2026.10.15."),
    _case("M03_1인당초과", {"verdict": "부적합", "unmet": ["C7"]}, "92,000원 ÷ 4명 = 23,000원",
          r_total="92,000원", attach_amount="92,000"),
    _case("M04_20시이후", {"verdict": "부적합", "unmet": ["C13"]}, "18:00~19:40 회의, 20:15 결제",
          datetime_place="2026. 10. 14.(화) 18:00~19:40 / 공과대학 7호관 세미나실", r_datetime="2026-10-14 20:15:03"),
    _case("M05_1시간초과", {"verdict": "부적합", "unmet": ["C14"]}, "16:30 종료, 18:10 결제 (100분 후)",
          datetime_place="2026. 10. 14.(화) 15:00~16:30 / 공과대학 7호관 세미나실", r_datetime="2026-10-14 18:10:44"),
    _case("M06_현금", {"verdict": "부적합", "unmet": ["C15", "C16"]}, "현금영수증, 카드번호 없음",
          r_title="[현금영수증]", r_method="현금", r_card=None),
    _case("M07_카드번호없음", {"verdict": "보완필요", "unmet": ["C16"]}, "카드 결제지만 영수증에 카드번호 없음", r_card=None),
    _case("M08_북구밖", {"verdict": "부적합", "unmet": ["C12"]}, "가맹점 주소 광주광역시 동구",
          r_address="광주광역시 동구 제봉로 0"),
    _case("M09_카페장소", {"verdict": "부적합", "unmet": ["C8"]}, "회의 장소가 카페",
          datetime_place="2026. 10. 14.(화) 17:00~18:30 / 스타벅스 전남대후문점"),
    _case("M10_서명누락_안내문", {"verdict": "보완필요", "unmet": ["C9", "C10"]}, "한 명 서명 없음, 회의내용에 안내문 남음",
          attendees=[("김가온", True), ("이나래", True), ("박다솜", False), ("최라온", True)],
          content=GUIDE + "\n기능 범위를 논의함"),
]


# ───────────────────────────── 그림 ─────────────────────────────
def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def photo_png(people: int, seed: int = 0) -> bytes:
    """회의 사진 대용: 칠판 앞 책상에 사람(원+몸통) people명."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (320, 200), (232, 236, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([20, 15, 300, 70], fill=(48, 84, 64))  # 칠판
    d.rectangle([30, 150, 290, 175], fill=(150, 110, 70))  # 책상
    for i in range(people):
        x = 40 + i * (240 // max(people, 1)) + seed
        d.ellipse([x, 90, x + 26, 116], fill=(240, 200, 160))
        d.rectangle([x - 4, 116, x + 30, 150], fill=(60 + 40 * i % 200, 90, 160))
    return _png(im)


def sign_png(seed: int) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (90, 34), (255, 255, 255))
    d = ImageDraw.Draw(im)
    pts = [(6 + k * 8, 17 + ((k * 7 + seed * 5) % 13) - 6) for k in range(10)]
    d.line(pts, fill=(20, 20, 90), width=2)
    return _png(im)


# ───────────────────────────── 문서 내용 → 공통 블록 ─────────────────────────────
TYPES_MINUTES = ["SW전공", "SW창업", "SW봉사"]
TYPES_ATTACH = ["SW전공", "SW창업", "SW봉사", "SW취업"]
FIELDS = ["코딩/알고리즘", "게임개발", "인공지능", "SW개발", "모빌리티"]


def _boxes(options, checked):
    return " ".join(("■ " if o == checked else "□ ") + o for o in options)


def build(case: dict) -> list[list]:
    att = case["attendees"]
    slots = att + [("", False)] * (6 - len(att))
    att_rows = []
    for k in range(3):
        row = []
        for name, signed in slots[2 * k : 2 * k + 2]:
            row.append(GCell(f"성명 {name}".strip()))
            row.append(GCell("(서명)", [sign_png(len(name) + k)] if name and signed else []))
        att_rows.append(row)
    att_rows[0].insert(0, GCell("참석자", rs=3))

    photos = [GCell("", [photo_png(len(att), s)], cs=2) for s in range(case["photos"])]
    photos += [GCell("(필수)", cs=2)] * (2 - len(photos))

    minutes = GTable(5, [
        [GCell("동아리 구분"), GCell(_boxes(TYPES_MINUTES, case["club_type"]), cs=4)],
        [GCell("동아리 분야"), GCell(_boxes(FIELDS, case["club_field"]) + "\n(전공동아리 신청시에만 작성)", cs=4)],
        [GCell("동아리명"), GCell(case["club_name"], cs=4)],
        *att_rows,
        [GCell("일시 및 장소"), GCell(case["datetime_place"], cs=4)],
        [GCell("회의 주제"), GCell(case["topic"], cs=4)],
        [GCell("회의내용"), GCell(case["content"], cs=4)],
        [GCell("회의 사진"), *photos],
    ])
    attach = GTable(5, [
        [GCell("동아리 구분"), GCell(_boxes(TYPES_ATTACH, case["club_type"]), cs=4)],
        [GCell("동아리 분야"), GCell(_boxes(FIELDS, case["club_field"]) + "\n(전공동아리 신청시에만 작성)", cs=4)],
        [GCell("동아리명"), GCell(case["club_name"], cs=4)],
        [GCell("날짜"), GCell(case["attach_date"]), GCell("금액"), GCell(f"{case['attach_amount']} 원", cs=2)],
    ])
    r = case["receipt"]
    labels = [("merchant", "가맹점명"), ("biz", "사업자번호"), ("address", "주소"), ("datetime", "거래일시"),
              ("card", "카드번호"), ("method", "결제수단"), ("approval", "승인번호"), ("total", "합계")]
    receipt = ([r["title"]] if "title" in r else []) + [f"{lab}: {r[k]}" for k, lab in labels if k in r]
    return [
        ["[붙임6] SW동아리 지출 증빙 서류", "2026년 전남대학교 소프트웨어중심대학사업단",
         f"SW동아리 회의비 지출 증빙 ( {case['round']} )차", minutes],
        ["2026년 전남대학교 소프트웨어중심대학사업단", "영수증 첨부철", attach, *receipt],
    ]


# ───────────────────────────── PDF / DOCX ─────────────────────────────
def write_pdf(doc) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    import tools.formkit  # noqa: F401  (나눔고딕 등록)

    st = ParagraphStyle("b", fontName="Nanum", fontSize=9.5, leading=13)
    W = [28 * mm, 38 * mm, 38 * mm, 38 * mm, 38 * mm]

    def flow(cell: GCell):
        items = [Paragraph(cell.text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), st)] if cell.text else []
        for png in cell.images:
            w, h = ImageReader(io.BytesIO(png)).getSize()
            scale = min(60 * mm / w, 1.0) if w > 200 else min(24 * mm / w, 1.0)
            items.append(RLImage(io.BytesIO(png), w * scale, h * scale))
        return items or ""

    story = []
    for pi, page in enumerate(doc):
        if pi:
            story.append(PageBreak())
        for block in page:
            if isinstance(block, str):
                story.append(Paragraph(block, st))
                continue
            grid = [[""] * block.cols for _ in block.rows]
            style = [("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
            for r, c, cell in block.placed():
                grid[r][c] = flow(cell)
                if cell.cs > 1 or cell.rs > 1:
                    style.append(("SPAN", (c, r), (c + cell.cs - 1, r + cell.rs - 1)))
            t = Table(grid, colWidths=W)
            t.setStyle(TableStyle(style))
            story.append(t)
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    return buf.getvalue()


def write_docx(doc) -> bytes:
    import docx
    from docx.enum.text import WD_BREAK
    from docx.shared import Mm

    d = docx.Document()
    for pi, page in enumerate(doc):
        for block in page:
            if isinstance(block, str):
                d.add_paragraph(block)
                continue
            t = d.add_table(rows=len(block.rows), cols=block.cols)
            t.style = "Table Grid"
            for r, c, cell in block.placed():
                tc = t.cell(r, c)
                if cell.cs > 1 or cell.rs > 1:
                    tc = tc.merge(t.cell(r + cell.rs - 1, c + cell.cs - 1))
                lines = cell.text.split("\n") if cell.text else [""]
                p = tc.paragraphs[0]
                p.text = lines[0]
                for ln in lines[1:]:
                    p = tc.add_paragraph(ln)
                for png in cell.images:
                    p.add_run().add_picture(io.BytesIO(png), width=Mm(60 if len(png) > 3000 else 24))
        if pi < len(doc) - 1:
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


WRITERS = {"hwp": write_hwp, "hwpx": write_hwpx, "pdf": write_pdf, "docx": write_docx}


def generate(out: Path, cases=CASES, formats=WRITERS) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for case in cases:
        doc = build(case)
        for ext in formats:
            p = out / f"{case['name']}.{ext}"
            p.write_bytes(WRITERS[ext](doc))
            paths.append(p)
    return paths


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "minutes"
    for p in generate(target):
        print(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p)
