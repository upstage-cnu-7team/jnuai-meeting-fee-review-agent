"""인공지능혁신융합대학사업단 '동아리 회의비 지출 증빙(별첨 1-1)' 가상 샘플을 HWP·PDF·DOCX 세 형식으로 같은 내용으로 만든다.

- HWP: 실제 빈 양식 HWP(별첨 1-1)를 템플릿으로 받아 칸 문단의 글자를 바꾸고, 영수증·서명 그림을 원본 그림 개체 구조로
  끼워 넣는다. 서식(DocInfo)은 원본 그대로라 한글·Upstage가 정상 파일로 연다.
- PDF(reportlab)·DOCX(python-docx): 같은 표 구성을 재현한다.
- 영수증은 가상 카드 매출전표 이미지(PIL)다. 모든 이름·학번·가맹점·카드번호·승인번호는 가상이다.

    python tools/aicollege_samples.py <빈 양식 별첨1-1.hwp> [출력 폴더]
"""
from __future__ import annotations

import copy
import io
import struct
import sys
import zlib
from datetime import date
from pathlib import Path

import olefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from minutes_review.extract.hwp import records  # noqa: E402
from tools.hwpkit import write_cfb  # noqa: E402

FONT = ROOT / "assets" / "fonts" / "NanumGothic-Regular.ttf"
FONT_B = ROOT / "assets" / "fonts" / "NanumGothic-Bold.ttf"
WEEK = "월화수목금토일"

# ───────────────────────────── 샘플 내용 ─────────────────────────────
BASE = {
    "team": "코드메이트",
    "title": "웹 서비스 MVP 기능 범위 확정 회의",
    "date": date(2026, 10, 14),
    "start": "17:00",
    "end": "18:30",
    "place": "공과대학 7호관 501호 세미나실",
    "content": [
        "1. 지난주 사용자 인터뷰 결과 공유: 일정 공유 기능 요구가 가장 많았음",
        "2. MVP 범위를 일정 등록·공유·알림 3개 기능으로 확정, 프론트 2명·백엔드 2명 담당 배정",
        "3. 결과: 10월 28일까지 화면 설계, 11월 4일까지 API 초안 완성하기로 결정",
    ],
    "attendees": [  # (소속, 학번, 이름, 서명)
        ("인공지능학부", "202400001", "김가온", True),
        ("인공지능학부", "202400002", "이나래", True),
        ("소프트웨어공학과", "202400003", "박다솜", True),
        ("소프트웨어공학과", "202400004", "최라온", True),
    ],
    "writer": "김가온",
    "amount": "60,000",
    "payer": ("인공지능학부", "김가온", True),
    "submitted_at": "2026-10-16 10:00",  # 메일 접수 일시 (서류 밖 정보)
    "receipt": {
        "title": "신용카드 매출전표",
        "merchant": "가온분식 용봉점",
        "biz": "000-00-00000",
        "address": "광주광역시 북구 용봉로 0",
        "card_type": "가상은행 연구비카드",
        "card_no": "5310-12**-****-3456",
        "datetime": "2026-10-14 18:42:10",
        "approval": "30012345",
        "items": [("김밥", 4, 16000), ("라면", 4, 24000), ("떡볶이", 2, 20000)],
        "total": 60000,
    },
}


def case(name: str, note: str, **change) -> dict:
    c = copy.deepcopy(BASE)
    for k, v in change.items():
        if k.startswith("r_"):
            if v is None:
                c["receipt"].pop(k[2:], None)
            else:
                c["receipt"][k[2:]] = v
        else:
            c[k] = v
    c.update(name=name, note=note)
    return c


SNACK = [("아메리카노", 4, 12000), ("쿠키", 4, 10000), ("샌드위치", 2, 12000)]

# expect: 이 케이스가 걸려야 하는 조건 (오프라인 기대값). submitted_at: 메일 접수 일시 (R17)
CASES = [
    case("A01_정상", "모든 기준 충족", expect=[]),
    case("A02_날짜불일치", "회의 10.14, 결제 10.15 (다음 날 결제라 식비 결제 시각도 위반)", expect=["R04", "R09"],
         r_datetime="2026-10-15 18:42:10"),
    case("A03_주말", "토요일 회의·결제", expect=["R05"], date=date(2026, 10, 17), r_datetime="2026-10-17 18:42:10",
         submitted_at="2026-10-19 10:00"),
    case("A04_20시이후", "18:30~20:00 회의, 20:25 결제", expect=["R06"], start="18:30", end="20:00",
         r_datetime="2026-10-14 20:25:31"),
    case("A05_주류", "호프집, 맥주 결제", expect=["R07"], r_merchant="가온호프 용봉점",
         r_items=[("치킨", 2, 36000), ("생맥주", 4, 24000)]),
    case("A06_1인당초과", "92,000원 ÷ 4명", expect=["R08"], amount="92,000",
         r_items=[("삼겹살", 8, 72000), ("공기밥", 4, 4000), ("냉면", 4, 16000)], r_total=92000),
    case("A07_식비1시간초과", "18:30 종료, 19:50 결제 (80분 후)", expect=["R09"], r_datetime="2026-10-14 19:50:12"),
    case("A08_다과비시각", "다과비인데 회의 60분 전 결제 (기준 30분)", expect=["R09"], start="16:00", end="17:30",
         r_merchant="가온베이커리 용봉점", r_items=SNACK, r_total=34000, amount="34,000", r_datetime="2026-10-14 15:00:05"),
    case("A09_회의1시간미만", "17:00~17:40 회의", expect=["R10"], end="17:40", r_datetime="2026-10-14 18:00:44"),
    case("A10_북구밖", "광주광역시 동구 가맹점", expect=["R11"], r_address="광주광역시 동구 제봉로 0"),
    case("A11_카페장소", "회의 장소가 카페", expect=["R12"], place="가온카페 용봉점 2층"),
    case("A12_간이영수증", "간이영수증, 카드·승인번호 없음", expect=["R02", "R03"], r_title="간이영수증",
         r_card_type=None, r_card_no=None, r_approval=None),
    case("A13_서명누락", "참석자 1명 서명 없음", expect=["R14"],
         attendees=BASE["attendees"][:2] + [("소프트웨어공학과", "202400003", "박다솜", False)] + BASE["attendees"][3:]),
    case("A14_금액불일치", "사용 비용 65,000원 ≠ 영수증 60,000원", expect=["R15"], amount="65,000"),
    case("A15_제출기한초과", "10.14 사용 → 7일째(10.21) 18:30 접수", expect=["R17"], submitted_at="2026-10-21 18:30"),
    case("A16_회의내용부실", "회의내용 한 줄", expect=["R13"], content=["회의함"]),
    case("A17_결제자서명누락", "결제자 서명 칸 비어 있음", expect=["R16"], payer=("인공지능학부", "김가온", False)),
    case("A18_워드서명", "참석자 1명이 서명 칸에 이름을 타자로 침 (워드작성 서명 불가)", expect=["R14"],
         attendees=BASE["attendees"][:3] + [("소프트웨어공학과", "202400004", "최라온", "typed")]),
]


def when(c: dict) -> str:
    if c.get("when_text"):  # 학생이 쓰는 다른 표기 시험용 (예: '10월 14일(수) 오후 5시~6시 30분')
        return c["when_text"]
    d = c["date"]
    return f"{d:%Y.%m.%d}.({WEEK[d.weekday()]}), {c['start']}~{c['end']}"


# ───────────────────────────── 그림 ─────────────────────────────
def _png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def receipt_png(r: dict) -> bytes:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    lines = [("b", r["title"]), ("-", ""), ("", f"가맹점명: {r['merchant']}"), ("", f"사업자번호: {r['biz']}"),
             ("", f"주소: {r['address']}"), ("-", "")]
    if r.get("card_type"):
        lines.append(("", f"카드종류: {r['card_type']}"))
    if r.get("card_no"):
        lines.append(("", f"카드번호: {r['card_no']}"))
    lines.append(("", f"거래일시: {r['datetime']}"))
    if r.get("approval"):
        lines.append(("", f"승인번호: {r['approval']}"))
    lines.append(("-", ""))
    lines += [("item", it) for it in r["items"]]
    lines += [("-", ""), ("b", f"합계 {r['total']:,}원"), ("", "감사합니다")]
    W, lh = 520, 34
    im = Image.new("RGB", (W, 40 + lh * len(lines)), (252, 251, 246))
    d = ImageDraw.Draw(im)
    f, fb = ImageFont.truetype(str(FONT), 21), ImageFont.truetype(str(FONT_B), 25)
    y = 20
    for kind, t in lines:
        if kind == "-":
            d.line([(20, y + lh // 2), (W - 20, y + lh // 2)], fill=(90, 90, 90), width=1)
        elif kind == "b":
            d.text((W // 2, y), t, font=fb, fill=(20, 20, 20), anchor="ma")
        elif kind == "item":
            n, q, a = t
            d.text((24, y), n, font=f, fill=(25, 25, 25))
            d.text((330, y), str(q), font=f, fill=(25, 25, 25))
            d.text((W - 24, y), f"{a:,}", font=f, fill=(25, 25, 25), anchor="ra")
        else:
            d.text((24, y), t, font=f, fill=(25, 25, 25))
        y += lh
    im = im.rotate(1.2, expand=True, fillcolor=(255, 255, 255)).filter(ImageFilter.GaussianBlur(0.4))
    if r.get("blur"):  # 흐리게 찍힌 영수증 사진: 크게 번지고 대비가 낮음
        from PIL import ImageEnhance

        im = ImageEnhance.Contrast(im.resize((im.width // 4, im.height // 4)).resize(im.size).filter(ImageFilter.GaussianBlur(4))).enhance(0.35)
    return _png(im)


def sign_png(seed: int) -> bytes:
    from PIL import Image, ImageDraw

    # 작고 흐린 서명은 추출이 '서명 없음'으로 읽은 사례가 있어 크고 진하게 그린다
    im = Image.new("RGB", (240, 80), (255, 255, 255))
    d = ImageDraw.Draw(im)
    pts = [(14 + k * 20, 38 + ((k * 7 + seed * 5) % 31) - 15) for k in range(11)]
    d.line(pts, fill=(15, 15, 90), width=6)
    d.line([(24, 64), (210, 56)], fill=(15, 15, 90), width=4)
    return _png(im)


def sign_cell(signed, name: str, seed: int) -> tuple[str, list]:
    """서명 칸 내용: True=서명 그림, False=빈 칸, "typed"=이름을 타자로 입력(워드 작성 서명)."""
    if signed == "typed":
        return name, []
    return "", [(sign_png(seed), 20)] if signed else []


# ───────────────────────────── HWP (실제 양식에 채우기) ─────────────────────────────
PH, PT, CTRL, LIST, SHP, PIC = 66, 67, 71, 72, 76, 85
MM = 7200 / 25.4  # HWPUNIT


def _rec(tag, level, body):
    if len(body) >= 0xFFF:
        return struct.pack("<II", tag | (level << 10) | (0xFFF << 20), len(body)) + body
    return struct.pack("<I", tag | (level << 10) | (len(body) << 20)) + body


def _z(b):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(b) + c.flush()


GSO_CHARS = struct.pack("<H", 11) + b" osg" + b"\0" * 8 + struct.pack("<H", 11)


def _gso(level: int, bid: int, w_mm: float, png: bytes, inst: int) -> bytes:
    """그림 개체 (원본 양식의 그림 개체와 같은 배치: 개체 공통 + 그리기 개체 + 그림)."""
    from PIL import Image

    iw, ih = Image.open(io.BytesIO(png)).size
    w = int(w_mm * MM)
    h = int(w * ih / iw)
    desc = "그림".encode("utf-16-le")
    attr = 0x042A2311  # 원본 속성 + '글자처럼 취급'(bit0) → 칸 안에서 글자처럼 놓인다
    common = struct.pack("<IIIIIIHHHHII", attr, 0, 0, w, h, 15, 0, 0, 0, 0, inst, 0)
    head = b" osg" + common + struct.pack("<H", 2) + desc
    # 원본 크기(그림 픽셀 × 75 HWPUNIT, 96dpi 기준) → 표시 크기로 줄이는 비율. 자르기·사각형 좌표는 원본 크기 단위다
    ow, oh = iw * 75, ih * 75
    ident = struct.pack("<6d", 1, 0, 0, 0, 1, 0)
    scale = struct.pack("<6d", w / ow, 0, 0, 0, h / oh, 0)
    comp = (b"cip$cip$" + struct.pack("<iiHH", 0, 0, 0, 1) + struct.pack("<IIII", ow, oh, w, h)
            + struct.pack("<IH", 0, 0) + struct.pack("<ii", w // 2, h // 2) + struct.pack("<H", 1) + ident + scale + ident)
    rect = struct.pack("<8i", 0, 0, ow, 0, ow, oh, 0, oh)
    pic = bytes(12) + rect + struct.pack("<4i", 0, 0, ow, oh) + bytes(8) + struct.pack("<bbBH", 0, 0, 0, bid) + bytes(1) + struct.pack("<I", inst) + bytes(13)  # 원본과 같은 91바이트
    return _rec(CTRL, level, head) + _rec(SHP, level + 1, comp) + _rec(PIC, level + 2, pic)


class HwpFiller:
    def __init__(self, template: bytes):
        ole = olefile.OleFileIO(io.BytesIO(template))
        self.streams = {"/".join(p): ole.openstream(p).read() for p in ole.listdir()}
        self.compressed = bool(struct.unpack_from("<I", self.streams["FileHeader"], 36)[0] & 1)
        sec = self._dec(self.streams["BodyText/Section0"])
        self.recs = [list(r) for r in records(sec)]
        self.bins: list[bytes] = []
        self.next_bid = sum(1 for t, *_ in records(self._dec(self.streams["DocInfo"])) if t == 18) + 1
        self.inst = 0x6C000000

    def _dec(self, b):
        return zlib.decompress(b, -15) if self.compressed else b

    def _enc(self, b):
        return _z(b) if self.compressed else b

    def cells(self, table_no: int) -> dict[tuple[int, int], list[int]]:
        """표 번호(0부터) → {(열, 행): [그 칸의 PARA_HEADER 레코드 위치들]}."""
        out, t, cur, tlevel = {}, -1, None, None
        for i, (tag, lvl, body) in enumerate(self.recs):
            if tag == CTRL and body[:4] == b" lbt":
                t += 1
                tlevel = lvl
                continue
            if tlevel is not None and lvl <= tlevel:
                tlevel = None
            if t == table_no and tlevel is not None:
                if tag == LIST and lvl == tlevel + 1:
                    cur = struct.unpack_from("<HH", body, 8)
                    out[cur] = []
                elif tag == PH and lvl == tlevel + 1 and cur is not None:
                    out[cur].append(i)
        return out

    def set_para(self, ph: int, text: str, images: list[tuple[bytes, float]] = ()) -> None:
        """PARA_HEADER 위치의 문단 글자를 바꾸고 그림을 붙인다 (기존 그림·컨트롤은 없는 칸만 대상)."""
        level = self.recs[ph][1]
        body = b"".join(GSO_CHARS for _ in images) + text.encode("utf-16-le") + struct.pack("<H", 13)
        head = bytearray(self.recs[ph][2])
        old = struct.unpack_from("<I", head, 0)[0]
        struct.pack_into("<I", head, 0, (old & 0x80000000) | (len(body) // 2))
        mask = struct.unpack_from("<I", head, 4)[0]
        struct.pack_into("<I", head, 4, mask | (0x800 if images else 0))
        self.recs[ph][2] = bytes(head)
        j = ph + 1
        has_pt = j < len(self.recs) and self.recs[j][0] == PT and self.recs[j][1] == level + 1
        if len(body) == 2:  # 빈 문단: 한글은 PARA_TEXT 레코드를 아예 두지 않는다 (있으면 손상 파일로 취급됨)
            if has_pt:
                del self.recs[j]
        elif has_pt:
            self.recs[j][2] = body
        else:
            self.recs.insert(j, [PT, level + 1, body])
        # 짧은 값으로 바꾸면 원래 글자 모양 구간이 새 문단 길이를 넘어갈 수 있다.
        # WE-Meet 작성자 칸은 여러 서식 구간을 가져 한컴 보안 검사에서 손상 경고가 난다.
        for idx in range(ph + 1, len(self.recs)):
            tag, lvl, data = self.recs[idx]
            if lvl <= level:
                break
            if lvl == level + 1 and tag in (68, 69):
                stride, count_offset = (8, 12) if tag == 68 else (36, 16)
                kept = [data[k:k + stride] for k in range(0, len(data), stride)
                        if struct.unpack_from("<I", data, k)[0] < len(body) // 2]
                self.recs[idx][2] = b"".join(kept)
                head = bytearray(self.recs[ph][2])
                struct.pack_into("<H", head, count_offset, len(kept))
                self.recs[ph][2] = bytes(head)
        # 문단 끝(PCS·PLS 등 바로 하위 레코드) 뒤에 그림 개체를 넣는다
        k = j + 1
        while k < len(self.recs) and self.recs[k][1] > level and self.recs[k][0] in (68, 69, 70):
            k += 1
        for png, w_mm in images:
            self.bins.append(png)
            bid = self.next_bid
            self.next_bid += 1
            self.inst += 1
            gso = list(records(_gso(level + 1, bid, w_mm, png, self.inst)))
            self.recs[k:k] = [list(r) for r in gso]
            k += len(gso)

    def fill(self, table_no: int, col: int, row: int, lines: list[str] | str, images=()) -> None:
        paras = self.cells(table_no)[(col, row)]
        lines = [lines] if isinstance(lines, str) else lines
        # 줄 수보다 문단이 많으면 남는 문단은 비우고, 모자라면 마지막 문단에 이어 쓴다
        for n, ph in enumerate(paras):
            if n < len(lines):
                text = lines[n] if n < len(paras) - 1 else " ".join(lines[n:])
            else:
                text = ""
            self.set_para(self.cells(table_no)[(col, row)][n], text, images if n == 0 else ())

    def build(self) -> bytes:
        s = dict(self.streams)
        s["BodyText/Section0"] = self._enc(b"".join(_rec(t, l, b) for t, l, b in self.recs))
        if self.bins:
            di = [list(r) for r in records(self._dec(s["DocInfo"]))]
            idmap = next(r for r in di if r[0] == 17)
            body = bytearray(idmap[2])
            struct.pack_into("<i", body, 0, struct.unpack_from("<i", body, 0)[0] + len(self.bins))
            idmap[2] = bytes(body)
            last = max(i for i, r in enumerate(di) if r[0] == 18)
            first_new = self.next_bid - len(self.bins)
            new = [[18, 1, struct.pack("<HHH", 0x0001, first_new + k, 3) + "png".encode("utf-16-le")] for k in range(len(self.bins))]
            di[last + 1 : last + 1] = new
            s["DocInfo"] = self._enc(b"".join(_rec(t, l, b) for t, l, b in di))
            for k, png in enumerate(self.bins):
                s[f"BinData/BIN{first_new + k:04X}.png"] = self._enc(png)
        return write_cfb(s)


def write_hwp(c: dict, template: bytes) -> bytes:
    f = HwpFiller(template)
    f.fill(0, 1, 1, c["team"])
    f.fill(0, 1, 2, c["title"])
    f.fill(0, 1, 3, when(c))
    f.fill(0, 5, 3, c["place"])
    f.fill(0, 1, 4, c["content"] + [""])
    for k, (aff, sid, name, signed) in enumerate(c["attendees"]):
        row = 6 + k
        f.fill(0, 1, row, aff)
        f.fill(0, 2, row, sid)
        f.fill(0, 4, row, name)
        f.fill(0, 6, row, *sign_cell(signed, name, k))
    for row in range(6 + len(c["attendees"]), 8):  # 양식 안내 문구가 있는 서명 칸은 비운다
        f.fill(0, 6, row, "")
    d = c["date"]
    f.fill(0, 0, 12, f"2026년 {d.month}월 {d.day}일    작성자 : {c['writer']} ( 인 )")
    if c["receipt"] is None:  # 영수증을 붙이지 않음 (안내 글은 그대로)
        f.fill(1, 0, 1, ["영수증 첨부란", "(연구비카드 매출전표)"])
    else:
        f.fill(1, 0, 1, ["", ""], [(receipt_png(c["receipt"]), 60)])
    f.fill(1, 1, 2, f"{c['amount']} 원")
    aff, name, signed = c["payer"]
    f.fill(1, 1, 4, aff)
    f.fill(1, 2, 4, name)
    f.fill(1, 3, 4, *sign_cell(signed, name, 9))
    return f.build()


# ───────────────────────────── PDF / DOCX (같은 표 구성 재현) ─────────────────────────────
NOTICE = ["※ 회의내용은 구체적으로, 상세히 작성하시기 바랍니다.",
          "※ 회의 장소는 식당으로 기재하지 마시고, 연구실이나, 회의실, 실험실 등으로 기재하시기 바랍니다.",
          "※ 회의비 지출은 반드시 카드로 결제하여 사용하시기 바랍니다.(간이영수증 불인정, 주말 사용 불가)",
          "※ 일반식당 이외의 술집 등의 상호 및 주류 포함 결제 내역은 지원되지 않으니 유의바랍니다."]


def _tables(c: dict):
    """[(열 수, [(행, 열, 텍스트, 그림[(png, mm)], 열병합, 행병합)])] — HWP 양식과 같은 칸 배치."""
    d = c["date"]
    t1 = [(0, 0, "동아리 회의비 지출 증빙", [], 7, 1),
          (1, 0, "팀명", [], 1, 1), (1, 1, c["team"], [], 6, 1),
          (2, 0, "회의명", [], 1, 1), (2, 1, c["title"], [], 6, 1),
          (3, 0, "회의일시", [], 1, 1), (3, 1, when(c), [], 2, 1), (3, 3, "회의장소", [], 2, 1), (3, 5, c["place"], [], 2, 1),
          (4, 0, "회의내용", [], 1, 1), (4, 1, "\n".join(c["content"]), [], 6, 1),
          (5, 0, "참석자 명단", [], 1, 7), (5, 1, "소속", [], 1, 1), (5, 2, "학번", [], 2, 1), (5, 4, "이름", [], 2, 1), (5, 6, "서명", [], 1, 1)]
    for k in range(6):
        a = c["attendees"][k] if k < len(c["attendees"]) else ("", "", "", False)
        t1 += [(6 + k, 1, a[0], [], 1, 1), (6 + k, 2, a[1], [], 2, 1), (6 + k, 4, a[2], [], 2, 1),
               (6 + k, 6, *sign_cell(a[3], a[2], k), 1, 1)]
    t1.append((12, 0, f"2026년 {d.month}월 {d.day}일    작성자 : {c['writer']} ( 인 )", [], 7, 1))
    aff, name, signed = c["payer"]
    t2 = [(0, 0, "영수증", [], 4, 1), (1, 0, "", [(receipt_png(c["receipt"]), 60)], 4, 1),
          (2, 0, "사용 비용", [], 1, 1), (2, 1, f"{c['amount']} 원", [], 3, 1),
          (3, 0, "결제자", [], 1, 2), (3, 1, "소속", [], 1, 1), (3, 2, "이름", [], 1, 1), (3, 3, "서명", [], 1, 1),
          (4, 1, aff, [], 1, 1), (4, 2, name, [], 1, 1), (4, 3, *sign_cell(signed, name, 9), 1, 1),
          (5, 0, "\n".join(NOTICE), [], 4, 1)]
    return [(7, t1, "[별첨 1-1.] 동아리 회의비 지출 증빙"), (4, t2, None)]


def write_pdf(c: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    import tools.formkit  # noqa: F401  (나눔고딕 등록)

    st = ParagraphStyle("b", fontName="Nanum", fontSize=9.5, leading=13)
    story = []
    for n, (cols, cells, head) in enumerate(_tables(c)):
        if n:
            story.append(PageBreak())
        if head:
            story.append(Paragraph(head, st))
        rows = 1 + max(r for r, *_ in cells)
        grid = [[""] * cols for _ in range(rows)]
        style = [("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
        for r, col, text, imgs, cs, rs in cells:
            items = [Paragraph(text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br/>"), st)] if text else []
            for png, w_mm in imgs:
                iw, ih = ImageReader(io.BytesIO(png)).getSize()
                items.append(RLImage(io.BytesIO(png), w_mm * mm, w_mm * mm * ih / iw))
            grid[r][col] = items or ""
            if cs > 1 or rs > 1:
                style.append(("SPAN", (col, r), (col + cs - 1, r + rs - 1)))
        t = Table(grid, colWidths=[180 * mm / cols] * cols)
        t.setStyle(TableStyle(style))
        story.append(t)
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=12 * mm).build(story)
    return buf.getvalue()


def write_docx(c: dict) -> bytes:
    import docx
    from docx.enum.text import WD_BREAK
    from docx.shared import Mm

    d = docx.Document()
    for n, (cols, cells, head) in enumerate(_tables(c)):
        if n:
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        if head:
            d.add_paragraph(head)
        rows = 1 + max(r for r, *_ in cells)
        t = d.add_table(rows=rows, cols=cols)
        t.style = "Table Grid"
        for r, col, text, imgs, cs, rs in cells:
            cell = t.cell(r, col)
            if cs > 1 or rs > 1:
                cell = cell.merge(t.cell(r + rs - 1, col + cs - 1))
            lines = text.split("\n") if text else [""]
            p = cell.paragraphs[0]
            p.text = lines[0]
            for ln in lines[1:]:
                p = cell.add_paragraph(ln)
            for png, w_mm in imgs:
                p.add_run().add_picture(io.BytesIO(png), width=Mm(w_mm))
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def generate(template: Path, out: Path, cases=CASES) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    tpl = template.read_bytes()
    paths = []
    for c in cases:
        for ext, data in (("hwp", write_hwp(c, tpl)), ("pdf", write_pdf(c)), ("docx", write_docx(c))):
            p = out / f"{c['name']}.{ext}"
            p.write_bytes(data)
            paths.append(p)
    return paths


if __name__ == "__main__":
    tpl = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "samples" / "aicollege"
    for p in generate(tpl, out):
        print(p)
