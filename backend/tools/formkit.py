"""취업동아리 첨부 양식(붙임1~8)을 HWP 원본 구성 그대로 PDF로 그리는 도구.

- 빈 양식(공고 패키지용)과 가상 데이터를 채운 제출 서류(샘플용) 모두 같은 함수로 만든다.
- 모든 인적 사항은 가상 데이터다. 사진·서명·영수증 이미지는 회색 자리표시 상자로 대신한다.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
FONT_DIR = ROOT / "assets" / "fonts"
pdfmetrics.registerFont(TTFont("Nanum", str(FONT_DIR / "NanumGothic-Regular.ttf")))
pdfmetrics.registerFont(TTFont("NanumB", str(FONT_DIR / "NanumGothic-Bold.ttf")))

INK = colors.HexColor("#1f2937")
LINE = colors.HexColor("#4b5563")
HEAD_BG = colors.HexColor("#e8eef7")
PHOTO_BG = colors.HexColor("#d1d5db")

S = {
    "body": ParagraphStyle("body", fontName="Nanum", fontSize=9.5, leading=14, textColor=INK),
    "small": ParagraphStyle("small", fontName="Nanum", fontSize=8.5, leading=12, textColor=INK),
    "label": ParagraphStyle("label", fontName="NanumB", fontSize=9.5, leading=13, alignment=TA_CENTER),
    "attach": ParagraphStyle("attach", fontName="NanumB", fontSize=11, leading=15),
    "title": ParagraphStyle("title", fontName="NanumB", fontSize=15, leading=21, alignment=TA_CENTER),
    "center": ParagraphStyle("center", fontName="Nanum", fontSize=10, leading=15, alignment=TA_CENTER),
}

YEAR_HEAD = "2026년 전남대학교 소프트웨어중심대학사업단"


def P(text, style="body"):
    text = "" if text is None else str(text)
    return Paragraph(text.replace("\n", "<br/>"), S[style])


def L(text):
    return P(text, "label")


def grid(data, widths, *, head_cols=(), head_rows=(), spans=(), heights=None, valign="MIDDLE"):
    t = Table(data, colWidths=widths, rowHeights=heights)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.6, LINE),
        ("VALIGN", (0, 0), (-1, -1), valign),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    for c in head_cols:
        style.append(("BACKGROUND", (c, 0), (c, -1), HEAD_BG))
    for r in head_rows:
        style.append(("BACKGROUND", (0, r), (-1, r), HEAD_BG))
    for sp in spans:
        style.append(("SPAN", sp[0], sp[1]))
    t.setStyle(TableStyle(style))
    return t


def title_band(name):
    t = Table([[P(f"{YEAR_HEAD}\n{name}", "title")]], colWidths=[170 * mm])
    t.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 1.2, LINE),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f6fb")),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return [t, Spacer(1, 5 * mm)]


def photo_box(caption, w=78 * mm, h=38 * mm):
    t = Table([[P(caption, "center")]], colWidths=[w], rowHeights=[h])
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PHOTO_BG),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
            ]
        )
    )
    return t


def checks(options, chosen):
    return "  ".join(("■ " if o == chosen else "□ ") + o for o in options)


def sig(name):
    """서명 칸. 이름이 있으면 '홍길동 (서명)', 비어 있으면 빈칸 + (서명)."""
    return f"{name} (서명)" if name else "            (서명)"


CLUB_TYPES_FULL = ["SW전공", "SW창업", "SW봉사", "SW취업"]
CLUB_TYPES_NO_JOB = ["SW전공", "SW창업", "SW봉사"]  # 붙임6 회의비 증빙·붙임7 활동일지 원본 양식에는 SW취업이 없다
FIELDS = ["코딩/알고리즘", "게임개발", "인공지능", "SW개발", "모빌리티"]


# ───────────────────────────── 붙임1 ─────────────────────────────
def form1_application(d: dict | None):
    d = d or {}
    leader = d.get("leader", {})
    s = [P("[붙임1] SW동아리 지원 프로그램 신청서 및 계획서", "attach"), Spacer(1, 2 * mm)]
    s += title_band("SW동아리 지원 프로그램 신청서")
    W = [30 * mm, 30 * mm, 40 * mm, 25 * mm, 45 * mm]
    date = d.get("date") or "2026년    월    일"
    count = d.get("member_count")
    rows = [
        [L("동아리 구분"), P(checks(CLUB_TYPES_FULL, d.get("club_type"))), "", "", ""],
        [L("동아리 분야"), P(checks(FIELDS, d.get("field")) + "\n(전공동아리 신청시에만 작성)", "small"), "", "", ""],
        [L("신청이력"), P(checks(["신규", "기존"], d.get("history"))), "", "", ""],
        [L("동아리명"), P(d.get("club_name", "")), "", L("회원수"), P(f"총 {count if count is not None else '   '} 명")],
        [L("신청자\n(대표학생)"), L("소속학과(부)"), P(leader.get("dept", "")), L("학 년"), P(leader.get("grade", ""))],
        ["", L("학 번"), P(leader.get("sid", "")), L("성 명"), P(leader.get("name", ""))],
        ["", L("전화번호"), P(leader.get("phone", "")), L("이메일"), P(leader.get("email", ""))],
        [
            P(
                "상기와 같이 전남대학교 소프트웨어중심대학사업단\n동아리 지원 프로그램 신청서를 제출합니다.\n\n"
                f"동아리명: {d.get('club_name', '')}    대표학생: {sig(d.get('leader_sign'))}\n"
                f"지도교수: {sig(d.get('advisor_sign'))}\n\n{date}",
                "center",
            ),
            "", "", "", "",
        ],
        [P("전남대학교 소프트웨어중심대학사업단장 귀하", "center"), "", "", "", ""],
        [L("붙임서류"), P("1. [붙임2] 동아리 활동계획서\n2. [붙임3] 개인정보 수집·이용·제공 동의서\n3. [붙임5] 동아리 활동 서약서"), "", "", ""],
    ]
    spans = [((1, 0), (4, 0)), ((1, 1), (4, 1)), ((1, 2), (4, 2)), ((1, 3), (2, 3)), ((0, 4), (0, 6)),
             ((0, 7), (4, 7)), ((0, 8), (4, 8)), ((1, 9), (4, 9))]
    s.append(grid(rows, W, spans=spans))
    s.append(PageBreak())
    return s


def form1_plan(d: dict | None):
    d = d or {}
    s = title_band("SW동아리 활동 계획서")
    W = [32 * mm, 18 * mm, 120 * mm]
    m = d.get("months", {})
    overview = d.get("overview") or "※ 작성내용\n- 계획서는 A4 2매 이상 작성 요함\n1) 동아리의 목표\n2) 동아리의 활동 내역"
    common = "※ 공통사항: 소프트웨어중심대학사업단 프로그램 참여 계획\n(예시: TOPCIT, 국내외 인턴십/현장실습, SW프로그래밍 경진대회, 캡스톤 디자인 등)"
    if d.get("participation"):
        common += "\n" + d["participation"]
    rows = [
        [L("동아리 구분"), P(checks(CLUB_TYPES_FULL, d.get("club_type"))), ""],
        [L("동아리 분야"), P(checks(FIELDS, d.get("field")) + "\n(전공동아리 신청시에만 작성)", "small"), ""],
        [L("동아리 개요"), P(overview), ""],
        [L("활동계획"), P(common), ""],
        ["", P("※ 동아리활동 계획에 대해 기술\n" + d.get("activity_plan", "")), ""],
    ]
    spans = [((1, 0), (2, 0)), ((1, 1), (2, 1)), ((1, 2), (2, 2)), ((1, 3), (2, 3)), ((1, 4), (2, 4)), ((0, 3), (0, 4))]
    s.append(grid(rows, W, spans=spans))
    if d.get("long"):
        s.append(PageBreak())  # 계획서 2쪽째 (A4 2매 이상)
    rows2 = [
        [L("월별 운영계획"), L("9월"), P(m.get("9", ""))],
        ["", L("10월"), P(m.get("10", ""))],
        ["", L("11월"), P(m.get("11", ""))],
        [L("향후계획"), P("※ 작성내용\n- 기대효과 및 활용 방안에 대해 기술\n" + d.get("future", "")), ""],
    ]
    s.append(grid(rows2, W, spans=[((0, 0), (0, 2)), ((1, 3), (2, 3))]))
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임2 ─────────────────────────────
CONSENT_TEXT = (
    "본인은 전남대학교 소프트웨어중심대학사업단에서 진행하는 프로그램 운영과 관련하여 「개인정보보호법」 제15조, 제17조, "
    "제22조 및 제24조, 「국세기본법」 제81조의 13 제1항 제7호에 따라 아래와 같이 본인의 개인정보를 수집‧이용‧제공하는 것에 동의합니다."
)


def form2_consent(person: dict | None):
    person = person or {}
    agree = "■ 동의함 □ 동의하지 않음" if person.get("name") else "□ 동의함 □ 동의하지 않음"
    s = [P("[붙임2] 개인정보 및 과제정보 수집.이용.제공 동의서", "attach"), Spacer(1, 3 * mm)]
    s.append(P("개인정보 및 과세정보 수집ㆍ이용ㆍ제공 동의서", "title"))
    s.append(Spacer(1, 3 * mm))
    s.append(P(CONSENT_TEXT))
    s.append(Spacer(1, 3 * mm))
    blocks = [
        ("개인정보 수집 및 이용에 대한 동의", "○ 수집 목적: 소프트웨어중심대학사업 프로그램 운영 및 이수관리 등\n○ 수집 항목: 성명, 소속, 연락처, 전자우편, 영상물(사진 등) 등"),
        ("고유식별정보 처리 동의", "○ 처리 항목: 국가연구자번호"),
        ("민감정보 수집·이용 동의", "○ 목적: 프로그램 활동비, 전문가활용비 등의 비용 지급\n○ 항목: 주민번호, 계좌번호, 재학증명서"),
        ("개인정보의 제3자 제공에 대한 동의", "○ 제공받는 자: 과학기술정보통신부, 정보통신기획평가원 등"),
    ]
    for head, body in blocks:
        s.append(grid([[L(head)], [P(body + f"\n※ 동의하십니까? ( {agree} )")]], [170 * mm], head_rows=(0,)))
        s.append(Spacer(1, 2 * mm))
    s.append(Spacer(1, 4 * mm))
    s.append(
        grid(
            [[P(f"학과(전공): {person.get('dept', '')}    학번: {person.get('sid', '')}    성명: {sig(person.get('name'))}")]],
            [170 * mm],
        )
    )
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임3 ─────────────────────────────
def form3_pledge(d: dict | None):
    d = d or {}
    s = [P("[붙임3] SW동아리 활동 서약서 및 명단", "attach"), Spacer(1, 2 * mm)]
    s += title_band("SW동아리 활동 서약서")
    signs = d.get("signers", [])
    leader = d.get("leader_sign")
    lines = [f"대표학생 : {sig(leader)}"]
    for i in range(10):
        lines.append(f"참가학생 : {sig(signs[i] if i < len(signs) else None)}")
    body = (
        "본 동아리 회원들은 동아리 활동을 함에 있어 학칙에 위배되거나 학생 본분에 어긋나는 어떠한 행위도 하지 않을 것이며, "
        "만일 이를 어길시 동아리에 조치되는 어떠한 사항도 감수할 것임을 서약합니다.\n"
        "또한, 아래 조건에 따라 동아리 활동을 유지하지 못할 시 동아리 활동비 100% 환수에 동의합니다.\n"
        "· 동아리 성과공유회 참석 및 매월 동아리 활동일지 제출 필수\n"
        "· 동아리는 운영 기간 동안 유지해야 하며 동아리 활동이 유지되지 않을 시 이전 지급했던 동아리 활동비 환수(멤버교체가능)\n"
        "· 활동비 집행 내역을 투명하게 관리하고, 만약 개인 용도 사용 적발 시 전액 환수 (적발 시 추후 사업단 사업 참여 불가)\n\n"
        f"{d.get('date') or '2026년    월    일'}\n\n" + "\n".join(lines) +
        "\n\n※ 본 서약서는 동아리 활동 기간 중 유효하며, 회원전체에 적용 됨"
    )
    s.append(grid([[P(body)], [P("전남대학교 SW중심대학사업단장 귀하", "center")]], [170 * mm]))
    s.append(PageBreak())
    return s


def form3_roster(members: list | None, *, copy_note: str | None = None):
    members = members or []
    s = []
    if copy_note:
        s.append(P(copy_note, "small"))
        s.append(Spacer(1, 2 * mm))
    s += title_band("SW동아리 회원 명단")
    head = [L("순번"), L("학과(전공)명"), L("학번"), L("학년"), L("성명"), L("연락처"), L("E-mail")]
    rows = [head]
    for i in range(10):
        if i < len(members):
            m = members[i]
            rows.append([P(str(i + 1)), P(m.get("dept", ""), "small"), P(m.get("sid", ""), "small"), P(m.get("grade", ""), "small"),
                         P(m.get("name", "")), P(m.get("phone", ""), "small"), P(m.get("email", ""), "small")])
        else:
            placeholder = "대표자명" if i == 0 and not members else ("팀원명" if i in (1, 2) and not members else "")
            rows.append([P(str(i + 1)), P(placeholder), "", "", "", "", ""])
    by_grade = {g: 0 for g in ("1", "2", "3", "4")}
    etc = 0
    for m in members:
        g = str(m.get("grade", "")).strip()
        if g in by_grade:
            by_grade[g] += 1
        else:
            etc += 1
    total = len(members)
    rows.append([L("합 계"), L("1학년"), L("2학년"), L("3학년"), L("4학년"), L("기타"), L("총 인원(명)")])
    if members:
        rows.append(["", P(by_grade["1"]), P(by_grade["2"]), P(by_grade["3"]), P(by_grade["4"]), P(etc), P(total)])
    else:
        rows.append(["", "", "", "", "", "", ""])
    W = [12 * mm, 40 * mm, 22 * mm, 14 * mm, 20 * mm, 28 * mm, 34 * mm]
    s.append(grid(rows, W, head_rows=(0,), spans=[((0, 11), (0, 12))]))
    s.append(Spacer(1, 3 * mm))
    s.append(P("※ 졸업생, 타학교 학생, 일반인 참여 불가능\n※ 팀장(SW참여학과 필수), 팀원(타 학과도 가능)\n"
               "※ 휴학생, 타학과 학생의 경우 동아리 소속은 가능하나 활동비 및 소중마일리지 지급 불가", "small"))
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임4 ─────────────────────────────
def form4_id_bank(filled: bool):
    s = [P("[붙임4] 신분증 및 통장사본 첨부철", "attach"), Spacer(1, 2 * mm)]
    s += title_band("신분증 및 통장 사본 첨부철")
    for what in ("신분증 사본 1부", "통장 사본 1부"):
        s.append(P("■ " + what, "attach"))
        s.append(Spacer(1, 2 * mm))
        if filled:
            s.append(photo_box(f"[{what.split()[0]} {what.split()[1]} 이미지 — 가상 샘플]", 170 * mm, 55 * mm))
        else:
            s.append(grid([[P("※ 대표 1명만 제출(팀장)\n(해당 문구 삭제 후 제출)", "center")]], [170 * mm], heights=[55 * mm]))
        s.append(Spacer(1, 5 * mm))
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임5 ─────────────────────────────
def form5_cover(blank: bool):
    s = [P("[붙임5] 재학증명서 첨부철", "attach"), Spacer(1, 2 * mm)]
    s += title_band("재학증명서 첨부철")
    s.append(P("■ 재학증명서", "attach"))
    s.append(Spacer(1, 2 * mm))
    if blank:
        s.append(grid([[P("※ 2026년 3월 이후 발급만 인정\n※ 동아리 회원 전원 제출 필수\n(해당 문구 삭제 후 제출)", "center")]],
                      [170 * mm], heights=[80 * mm]))
    else:
        s.append(P("첨부: 다음 쪽부터 회원별 재학증명서", "body"))
    s.append(PageBreak())
    return s


def form5_certificate(c: dict):
    s = [Spacer(1, 10 * mm), P("재 학 증 명 서", "title"), Spacer(1, 3 * mm), P("(가상 샘플 — 실제 증명서 아님)", "center"), Spacer(1, 8 * mm)]
    rows = [
        [L("성 명"), P(c["name"]), L("학 번"), P(c["sid"])],
        [L("소 속"), P(c["dept"]), L("학 년"), P(c.get("grade", ""))],
        [L("학적 상태"), P(c.get("status", "재학")), L("발급일"), P(c["issued"])],
    ]
    s.append(grid(rows, [28 * mm, 57 * mm, 28 * mm, 57 * mm], head_cols=(0, 2)))
    s.append(Spacer(1, 15 * mm))
    s.append(P("위 사람은 본교에 재학 중임을 증명합니다.", "center"))
    s.append(Spacer(1, 10 * mm))
    s.append(P(f"발급일: {c['issued']}\n\n전남대학교총장 (직인 생략 — 가상)", "center"))
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임6 ─────────────────────────────
MEETING_GUIDE = (
    "※ 안내사항 숙지 후, 해당 내용은 지우고 회의내용 기록 ※\n"
    "▶ 회의일시와 회의비 영수증 날짜가 동일해야 함\n- 1일 1회, 1인당 2만원에 한하여 지원\n"
    "▶ 회의장소: 음식점, 카페X (ex. 강의실, 동아리실, 회의실 등)\n"
    "▶ 회의사진(필수): 음식점, 카페에서 찍은 사진 불가\n- 강의실, 동아리실, 회의실 등에서 촬영\n"
    "- 참석인원 모두 나오게 촬영(회의비 사용 인원수만큼)\n"
    "▶ 회의내용: 회의내용, 회의사진 및 결과를 상세히 기술"
)


def form6_meeting(m: dict | None, *, with_attach_label=False):
    m = m or {}
    s = []
    if with_attach_label:
        s += [P("[붙임6] SW동아리 지출 증빙 서류", "attach"), Spacer(1, 2 * mm)]
    s += title_band(f"SW동아리 회의비 지출 증빙 ( {m.get('no', ' ')} )차")
    names = m.get("attendees", [])
    cells = [f"{names[i]} (서명)" if i < len(names) else "(서명)" for i in range(10)]
    W = [28 * mm, 18 * mm, 53 * mm, 18 * mm, 53 * mm]
    rows = [
        [L("동아리 구분"), P(checks(CLUB_TYPES_NO_JOB, m.get("club_type"))), "", "", ""],
        [L("동아리 분야"), P(checks(FIELDS, None) + "\n(전공동아리 신청시에만 작성)", "small"), "", "", ""],
        [L("동아리명"), P(m.get("club_name", "")), "", "", ""],
    ]
    for r in range(5):
        rows.append([L("참석자") if r == 0 else "", L("성명"), P(cells[2 * r]), L("성명"), P(cells[2 * r + 1])])
    when = m.get("when", "")
    where = m.get("place", "")
    rows += [
        [L("일시 및 장소"), P(f"{when} / {where}" if when else ""), "", "", ""],
        [L("회의 주제"), P(m.get("topic", "")), "", "", ""],
        [L("회의내용"), P(m.get("content") or MEETING_GUIDE, "small"), "", "", ""],
    ]
    spans = [((1, 0), (4, 0)), ((1, 1), (4, 1)), ((1, 2), (4, 2)), ((0, 3), (0, 7)), ((1, 8), (4, 8)), ((1, 9), (4, 9)), ((1, 10), (4, 10))]
    s.append(grid(rows, W, spans=spans))
    photos = m.get("photos", 0)
    p1 = photo_box("[회의 사진 1 — 가상]") if photos >= 1 else P("(필수)", "center")
    p2 = photo_box("[회의 사진 2 — 가상]") if photos >= 2 else P("(필수)", "center")
    s.append(grid([[L("회의 사진"), p1, p2]], [28 * mm, 71 * mm, 71 * mm], heights=[44 * mm]))
    s.append(PageBreak())
    return s


def form6_receipt(r: dict | None):
    r = r or {}
    s = title_band("영수증 첨부철")
    W = [28 * mm, 52 * mm, 25 * mm, 65 * mm]
    rows = [
        [L("동아리 구분"), P(checks(CLUB_TYPES_FULL, r.get("club_type"))), "", ""],
        [L("동아리 분야"), P(checks(FIELDS, None) + "\n(전공동아리 신청시에만 작성)", "small"), "", ""],
        [L("동아리명"), P(r.get("club_name", "")), "", ""],
        [L("날짜"), P(r.get("date", "2026.00.00.")), L("금액"), P(f"{r['amount']:,}원" if r.get("amount") is not None else "원")],
    ]
    if r.get("amount") is None:
        rows.append([P("(※ 안내사항 숙지 후, 해당 내용은 지우고 제출)\n1. 해당 페이지 출력\n2. 영수증 원본 부착(가운데)\n3. 팀명/카드사용일/금액 작성 후 제출"), "", "", ""])
    else:
        rec = (
            f"<b>[영수증 원본 — 가상]</b>\n상호: {r['store']}\n거래일시: {r['date_time']}\n"
            + "\n".join(f"품목: {it}" for it in r["items"])
            + f"\n합계: {r['amount']:,}원\n결제: {r['payment']}"
        )
        rows.append([P(rec), "", "", ""])
    s.append(grid(rows, W, spans=[((1, 0), (3, 0)), ((1, 1), (3, 1)), ((1, 2), (3, 2)), ((0, 4), (3, 4))]))
    s.append(PageBreak())
    return s


def form6_purchase_request(d: dict | None):
    d = d or {}
    s = title_band("구매 요청서")
    W = [24 * mm, 40 * mm, 34 * mm, 26 * mm, 16 * mm, 30 * mm]
    items = d.get("items", [])
    rows = [
        [L("동아리구분"), P(d.get("club_type", "")), "", L("동아리 분야"), P("(전공동아리만 작성)", "small"), ""],
        [L("팀장명"), P(d.get("leader", "")), "", L("소속학과"), P(d.get("dept", "")), ""],
        [L("학 번"), P(d.get("sid", "")), "", L("연락처"), P(d.get("phone", "")), ""],
        [L("구매사유"), P(d.get("reason", "")), "", "", "", ""],
        [L("구매링크"), P("물품별로 각각 표시\n" + "\n".join(f"{i+1}. {it.get('link', '')}" for i, it in enumerate(items or [{}, {}]))), "", "", "", ""],
        [L("연번"), L("품 명"), L("옵 션"), L("단가"), L("수량"), L("금액")],
    ]
    for i in range(4):
        if i < len(items):
            it = items[i]
            rows.append([P(i + 1), P(it["name"]), P(it.get("option", "")), P(f"{it['price']:,}"), P(it["qty"]), P(f"{it['price'] * it['qty']:,}")])
        else:
            rows.append([P(i + 1), "", "", "", "", ""])
    total = sum(it["price"] * it["qty"] for it in items)
    rows.append([L("합 계"), P(f"{total:,}원" if items else ""), "", "", "", ""])
    spans = [((1, 0), (2, 0)), ((4, 0), (5, 0)), ((1, 1), (2, 1)), ((4, 1), (5, 1)), ((1, 2), (2, 2)), ((4, 2), (5, 2)),
             ((1, 3), (5, 3)), ((1, 4), (5, 4)), ((1, 10), (5, 10))]
    s.append(grid(rows, W, spans=spans))
    s.append(PageBreak())
    return s


def form6_purchase_proof(d: dict | None):
    d = d or {}
    s = title_band("구입 증빙서")
    W = [24 * mm, 50 * mm, 26 * mm, 70 * mm]
    rows = [
        [L("동아리구분"), P(d.get("club_type", "")), L("동아리 분야"), P("(전공동아리만 작성)", "small")],
        [L("팀장명"), P(sig(d.get("leader"))), L("소속학과"), P(d.get("dept", ""))],
        [L("학 번"), P(d.get("sid", "")), L("연락처"), P(d.get("phone", ""))],
        [L("활용계획"), P(d.get("plan", "")), "", ""],
    ]
    s.append(grid(rows, W, spans=[((1, 3), (3, 3))]))
    n = d.get("photos", 0)
    cells = [photo_box(f"[증빙사진 {i+1} — 가상]") if i < n else P(f"{i+1}.") for i in range(2)]
    s.append(grid([[L("증빙사진"), cells[0], cells[1]]], [24 * mm, 73 * mm, 73 * mm], heights=[44 * mm]))
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임7 ─────────────────────────────
def form7_activity_log(d: dict | None):
    d = d or {}
    s = [P("[붙임7] SW동아리 활동일지", "attach"), Spacer(1, 2 * mm)]
    month = d.get("month", " ")
    s += title_band(f"SW동아리 ( {month} )월 활동일지")
    W = [26 * mm, 22 * mm, 40 * mm, 82 * mm]
    attendees = d.get("attendees", [])
    rows = [
        [L("동아리 구분"), P(checks(CLUB_TYPES_NO_JOB, d.get("club_type", "SW전공" if not d else None))), "", ""],
        [L("동아리 분야"), P(checks(FIELDS, None) + "\n(전공동아리 신청시에만 작성)", "small"), "", ""],
        [L("동아리명"), P(d.get("club_name", "")), L("참석인원"), P(f"총 {len(attendees) if attendees else '   '} 명")],
        [L("참석자"), P(", ".join(attendees) if attendees else "참석자 전원 기재"), "", ""],
    ]
    spans = [((1, 0), (3, 0)), ((1, 1), (3, 1)), ((1, 3), (3, 3))]
    sessions = d.get("sessions") or [
        {"no": 1, "date": "2026.03.03.", "topic": "", "content": "활동내용"},
        {"no": 2, "date": "2026.03.03.", "topic": "", "content": "활동내용"},
        {"no": 3, "date": "2026.03.03.", "topic": "", "content": "활동내용"},
        {"no": 3, "date": "2026.03.03.", "topic": "", "content": "활동내용"},
    ]
    r = len(rows)
    for ss in sessions:
        rows.append([L("동아리\n활동 내용") if r == 4 else "", L("차시"), L("회의일시"), L("주제")])
        rows.append(["", P(f"{ss['no']}차시"), P(ss["date"]), P(ss.get("topic", ""))])
        rows.append(["", P(ss.get("content", "활동내용"), "small"), "", ""])
        spans.append(((1, r + 2), (3, r + 2)))
        r += 3
    spans.append(((0, 4), (0, r - 1)))
    s.append(grid(rows, W, spans=spans))
    if d.get("photos"):
        s.append(Spacer(1, 2 * mm))
        s.append(grid([[L("활동사진"), photo_box("[활동사진 — 가상]"), photo_box("[활동사진 — 가상]")]],
                      [26 * mm, 72 * mm, 72 * mm], heights=[42 * mm]))
    s.append(PageBreak())
    return s


# ───────────────────────────── 붙임8 ─────────────────────────────
def form8_expert(d: dict | None):
    d = d or {}
    s = [P("[붙임8] SW동아리 전문가 활용비 지급 신청서", "attach"), Spacer(1, 2 * mm)]
    s += title_band("SW동아리 전문가 활용비 지급신청서")
    W = [24 * mm, 36 * mm, 26 * mm, 30 * mm, 24 * mm, 30 * mm]
    rows = [
        [L("일 시"), P(d.get("date", "")), L("주민등록번호"), P("전부 기재" if not d else "******-*******"), L("입금은행\n계좌번호"), P(d.get("bank", ""))],
        [L("산업체 전문가"), P(d.get("expert", "")), L("직급"), P(d.get("position", "")), L("연락처"), P(d.get("phone", ""))],
        [L("일시"), P(d.get("when", "")), L("장소"), P(d.get("place", "")), "", ""],
        [L("자문내용"), P(d.get("content", "")), "", "", "", ""],
        [P("붙임. 이력서, 통장사본, 신분증, 개인정보 수집·이용·제공동의서 각 1부.\n위와 같이 2026년 전남대학교 소프트웨어중심대학사업 "
           "SW동아리 프로그램의 전문가 멘토링 보고서를 제출합니다.\n" + (d.get("sign_date") or "2026년 00월 00일") +
           f"\n산업체 전문가명: {d.get('expert', '')} (인)\n전남대학교 소프트웨어중심대학사업단장 귀하", "center"), "", "", "", "", ""],
    ]
    s.append(grid(rows, W, spans=[((3, 2), (5, 2)), ((1, 3), (5, 3)), ((0, 4), (5, 4))]))
    s.append(PageBreak())
    return s


# ───────────────────────────── 결과보고서 (가상 양식) ─────────────────────────────
def form_result_report(d: dict):
    """결과보고서는 공고에 형식이 없고 양식도 받지 못했다(PRD 3.11). 가상 양식임을 문서에 밝힌다."""
    s = [P("[결과보고서] ※ 사업단 양식 미확보 — 데모용 가상 양식", "attach"), Spacer(1, 2 * mm)]
    s += title_band("SW동아리 결과보고서")
    W = [34 * mm, 136 * mm]
    rows = [
        [L("동아리명"), P(d["club_name"])],
        [L("대표학생"), P(f"{d['leader_dept']} {d['leader']}")],
        [L("활동 기간"), P(d["period"])],
        [L("활동 요약"), P(d["summary"])],
        [L("취업교육 참여"), P(d["edu"])],
        [L("성과공유회 참가"), P(d["showcase"])],
        [L("주요 성과"), P(d["outcome"])],
    ]
    s.append(grid(rows, W, head_cols=(0,)))
    s.append(Spacer(1, 4 * mm))
    s.append(P("■ 월별 활동·지출 현황", "attach"))
    mrows = [[L("월"), L("활동 횟수"), L("지출액(원)")]]
    for m in d["monthly"]:
        mrows.append([P(m["month"]), P(m["count"]), P(f"{m['spent']:,}")])
    mrows.append([L("합계"), P(sum(m["count"] for m in d["monthly"])), P(f"{sum(m['spent'] for m in d['monthly']):,}")])
    s.append(grid(mrows, [40 * mm, 50 * mm, 80 * mm], head_rows=(0,)))
    s.append(Spacer(1, 4 * mm))
    s.append(grid([[L("비소모성 재료\n반납 확인"), P(d["return"])]], W))
    s.append(Spacer(1, 6 * mm))
    s.append(P(f"{d['date']}\n대표학생: {sig(d['leader'])}\n전남대학교 소프트웨어중심대학사업단장 귀하", "center"))
    s.append(PageBreak())
    return s


def build(path: Path, story: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    if story and isinstance(story[-1], PageBreak):
        story = story[:-1]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm, title=path.stem, author="sw-review-agent (가상 샘플)")
    doc.build(story)


__all__ = [n for n in dir() if n.startswith("form") or n in ("build", "P", "S", "grid", "title_band", "KeepTogether")]
