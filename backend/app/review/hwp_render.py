"""HWP 원본 모양 미리보기: HWP 안의 쪽 설정·표 칸(병합·너비·높이·테두리·배경)·글자 모양(크기·굵기·색)·문단 정렬을 읽어
reportlab으로 다시 그린다. 담당자가 한글에서 연 것과 같은 모양으로 보게 하려는 것이다.

minutes_review.extract.hwp(판정용 리더)는 칸 내용만 읽는다. 이 모듈은 화면용이라 모양 정보까지 읽는다.
참고: 한글과컴퓨터 'HWP 5.0 문서 파일 구조' — DocInfo의 BORDER_FILL·CHAR_SHAPE·PARA_SHAPE, BodyText의 PAGE_DEF·LIST_HEADER(표 칸).
글꼴은 나눔고딕 하나로 그린다(기울임 글꼴은 없어 색·굵기만 살린다).
"""
from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field

import olefile

from minutes_review.extract.hwp import (CHID_TABLE, CTRL_HEADER, LIST_HEADER, PARA_HEADER, PARA_TEXT, SHAPE_COMPONENT, SHAPE_PICTURE, _bin_image,
                                        _bin_streams, _fill_images, _picture, _stream, para_text, records, shape_rotation)

BORDER_FILL, CHAR_SHAPE, PARA_SHAPE = 0x10 + 4, 0x10 + 5, 0x10 + 9
PARA_CHAR_SHAPE, PAGE_DEF = 0x10 + 52, 0x10 + 57
LINE_MM = [0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
PT = 1 / 100  # HWPUNIT(1/7200인치) → pt


def _rgb(colorref: int) -> str:
    r, g, b = colorref & 0xFF, (colorref >> 8) & 0xFF, (colorref >> 16) & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


@dataclass
class Style:
    border_fills: list = field(default_factory=list)  # [(sides[(type,width,color)]*4 L,R,T,B, bg or None)]
    chars: list = field(default_factory=list)  # [(size_pt, bold, italic, color)]
    aligns: list = field(default_factory=list)  # ['LEFT'|'CENTER'|'RIGHT'|'JUSTIFY']


def _docinfo(data: bytes) -> Style:
    st = Style()
    for tag, _lvl, b in records(data):
        if tag == BORDER_FILL and len(b) >= 32:
            sides = [(b[2 + k * 6], b[3 + k * 6], struct.unpack_from("<I", b, 4 + k * 6)[0]) for k in range(4)]
            ft = struct.unpack_from("<I", b, 32)[0] if len(b) >= 36 else 0
            bg = _rgb(struct.unpack_from("<I", b, 36)[0]) if ft & 1 and len(b) >= 40 else None
            st.border_fills.append((sides, bg))
        elif tag == CHAR_SHAPE and len(b) >= 56:
            size = struct.unpack_from("<i", b, 42)[0] / 100
            attr = struct.unpack_from("<I", b, 46)[0]
            st.chars.append((size or 10, bool(attr & 2), bool(attr & 1), _rgb(struct.unpack_from("<I", b, 52)[0])))
        elif tag == PARA_SHAPE and len(b) >= 4:
            a = (struct.unpack_from("<I", b, 0)[0] >> 2) & 0x7
            st.aligns.append({1: "LEFT", 2: "RIGHT", 3: "CENTER"}.get(a, "JUSTIFY"))
    return st


@dataclass
class Para:
    text: str = ""
    char: int = 0
    align: int = 0


@dataclass
class CellBox:
    row: int
    col: int
    rspan: int
    cspan: int
    w: int
    h: int
    bf: int
    valign: str
    pad: tuple
    items: list = field(default_factory=list)  # Para | bytes(그림)


@dataclass
class TableBox:
    cells: list = field(default_factory=list)


class PageBreak:
    pass


@dataclass
class Pic:
    """글자처럼 취급하지 않은(떠 있는) 그림. 원래 크기(HWPUNIT)로 그린다."""
    data: bytes
    x: int = 0
    w: int = 0
    h: int = 0


@dataclass
class Chrome:
    """구역의 머리말·꼬리말 그림(사업단 로고 등). 매 쪽 위·아래에 원래 크기로 그린다."""
    head: list = field(default_factory=list)
    foot: list = field(default_factory=list)


def _shrunk(img, shrink):
    """큰 그림(휴대폰 사진·BMP)은 그리기 전에 줄인다. 큰 HWP를 다시 쓰지 않고 바로 PDF로 그리기 위해서다."""
    if shrink and img.data and len(img.data) > 500_000:
        try:
            img.data = shrink(img.data)
        except Exception:
            pass
    return img


def _parse(data: bytes, shrink=None):
    ole = olefile.OleFileIO(io.BytesIO(data))
    with ole:
        header = ole.openstream("FileHeader").read()
        compressed = bool(struct.unpack_from("<I", header, 36)[0] & 1)
        docinfo = _stream(ole, "DocInfo", compressed)
        st, bins, fills = _docinfo(docinfo), _bin_streams(ole, docinfo), _fill_images(docinfo)
        page_def, flow = None, []
        gso = (0, 0, 0)  # 바로 앞 그림 개체의 (x, 너비, 높이)
        rot = 0
        sections = sorted(("/".join(p) for p in ole.listdir() if len(p) == 2 and p[0] == "BodyText"),
                          key=lambda s: int(s.rsplit("Section", 1)[-1] or 0))
        for si, sec in enumerate(sections):
            if si:
                flow.append(PageBreak())
            stack: list[tuple[int, TableBox, CellBox | None]] = []  # (표 수준, 표, 현재 칸)
            cur_para: Para | None = None
            chrome, skip = Chrome(), None  # skip: (머리말·꼬리말 수준, 'head'|'foot')
            flow.append(chrome)
            for tag, level, r in records(_stream(ole, sec, compressed)):
                if tag == SHAPE_COMPONENT:  # 그림 회전각 (거꾸로 찍힌 영수증을 한글에서 돌려 놓은 경우)
                    rot = shape_rotation(r)
                # 머리말·꼬리말 안의 내용은 본문 흐름에 넣지 않는다 (그림만 쪽 위·아래에 그린다, VCCC·전자파 로고)
                if skip and level > skip[0]:
                    if tag == CTRL_HEADER and r[:4] == b" osg" and len(r) >= 24:
                        gso = (struct.unpack_from("<i", r, 12)[0], *struct.unpack_from("<II", r, 16))
                    elif tag == SHAPE_PICTURE:
                        img = _shrunk(_picture(ole, r, bins, compressed, rot), shrink)
                        if img.data:
                            getattr(chrome, skip[1]).append(Pic(img.data, *gso))
                    continue
                skip = None
                if tag == CTRL_HEADER and r[:4] in (b"daeh", b"toof"):
                    skip = (level, "head" if r[:4] == b"daeh" else "foot")
                    continue
                while stack and level <= stack[-1][0]:
                    lvl, tb, _ = stack.pop()
                    if not stack:
                        flow.append(tb)
                    else:  # 표 안의 표: 바깥 칸에 글로만 넣는다
                        pl, ptb, pc = stack[-1]
                        if pc is not None:
                            for c in tb.cells:
                                pc.items += [x for x in c.items if isinstance(x, Para)]
                target = stack[-1][2] if stack and stack[-1][2] is not None else None
                if tag == PAGE_DEF and page_def is None and len(r) >= 36:
                    page_def = struct.unpack_from("<9I", r, 0)
                elif tag == PARA_HEADER and len(r) >= 12:
                    if level == 0 and r[11] & 0x04 and any(not isinstance(x, Chrome) for x in flow):  # 문서 맨 앞 쪽 나눔은 빈 쪽
                        flow.append(PageBreak())
                    cur_para = Para(align=struct.unpack_from("<H", r, 8)[0])
                    (target.items if target is not None else flow).append(cur_para)
                elif tag == PARA_TEXT and cur_para is not None:
                    cur_para.text = para_text(r).rstrip("\r\n")
                elif tag == PARA_CHAR_SHAPE and cur_para is not None and len(r) >= 8:
                    cur_para.char = struct.unpack_from("<I", r, 4)[0]
                elif tag == CTRL_HEADER and r[:4] == CHID_TABLE:
                    stack.append((level, TableBox(), None))
                elif tag == LIST_HEADER and stack and level == stack[-1][0] + 1 and len(r) >= 34:
                    prop = struct.unpack_from("<I", r, 2)[0]
                    col, row, cspan, rspan = struct.unpack_from("<HHHH", r, 8)
                    w, h = struct.unpack_from("<II", r, 16)
                    pad = struct.unpack_from("<4H", r, 24)
                    bf = struct.unpack_from("<H", r, 32)[0]
                    cell = CellBox(row, col, max(rspan, 1), max(cspan, 1), w, h, bf, {1: "MIDDLE", 2: "BOTTOM"}.get((prop >> 5) & 3, "TOP"), pad)
                    lvl, tb, _ = stack[-1]
                    tb.cells.append(cell)
                    if bf in fills:  # 칸 배경 그림 (서명을 배경으로 넣은 경우)
                        img = _shrunk(_bin_image(ole, fills[bf], bins, compressed), shrink)
                        if img.data:
                            cell.items.append(img.data)
                    stack[-1] = (lvl, tb, cell)
                elif tag == CTRL_HEADER and r[:4] == b" osg" and len(r) >= 24:
                    gso = (struct.unpack_from("<i", r, 12)[0], *struct.unpack_from("<II", r, 16))
                elif tag == SHAPE_PICTURE:
                    img = _shrunk(_picture(ole, r, bins, compressed, rot), shrink)
                    if img.data:
                        if target is not None:
                            target.items.append(img.data)
                        else:  # 본문의 떠 있는 그림: 쪽 너비로 키우지 않고 원래 크기로
                            flow.append(Pic(img.data, *gso))
            while stack:
                lvl, tb, _ = stack.pop()
                if not stack:
                    flow.append(tb)
    return st, page_def, flow


def _sizes(cells, n, start, span, size) -> list[float | None]:
    """칸 크기(병합 포함)에서 줄·열 크기를 푼다. 한 칸짜리부터 정하고, 병합 칸은 모르는 줄이 하나 남을 때 뺀다."""
    out: list[float | None] = [None] * n
    for c in cells:
        if span(c) == 1:
            i = start(c)
            out[i] = max(out[i] or 0, size(c))
    for _ in range(n):
        changed = False
        for c in cells:
            idx = range(start(c), start(c) + span(c))
            unknown = [i for i in idx if out[i] is None]
            if len(unknown) == 1:
                out[unknown[0]] = max(size(c) - sum(out[i] for i in idx if out[i] is not None), 1)
                changed = True
        if not changed:
            break
    return out


def render_pdf(data: bytes, shrink=None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Flowable, Image, PageBreak as RLBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .pages import _esc, _fonts

    _fonts()
    st, pd, flow = _parse(data, shrink)
    W, H, ml, mr, mt, mb, mh, mf = (v * PT for v in (pd or (59528, 84186, 5669, 5669, 2834, 2834, 4252, 4252, 0))[:8])
    frame_w = W - ml - mr
    frame_h = H - mt - mb - mh - mf
    align_map = {"LEFT": TA_LEFT, "RIGHT": TA_RIGHT, "CENTER": TA_CENTER, "JUSTIFY": TA_JUSTIFY}
    cache: dict = {}

    def pstyle(p: Para) -> ParagraphStyle:
        size, bold, _italic, color = st.chars[p.char] if p.char < len(st.chars) else (10, False, False, "#000000")
        al = st.aligns[p.align] if p.align < len(st.aligns) else "JUSTIFY"
        key = (size, bold, color, al)
        if key not in cache:
            cache[key] = ParagraphStyle(f"s{len(cache)}", fontName="NanumB" if bold else "Nanum", fontSize=size, leading=size * 1.45,
                                        textColor=colors.HexColor(color), alignment=align_map[al])
        return cache[key]

    def para(p: Para):
        style = pstyle(p)
        if not p.text.strip():
            return Spacer(1, style.leading)
        return Paragraph(_esc(p.text).replace(" ", "&nbsp;") if p.text.startswith(" ") else _esc(p.text), style)

    def picture(raw: bytes, max_w: float, max_h: float):
        from PIL import Image as PILImage

        try:
            w, h = PILImage.open(io.BytesIO(raw)).size
        except Exception:
            return Spacer(1, 1)
        s = min(max_w / w, max_h / h)
        return Image(io.BytesIO(raw), width=w * s, height=h * s)

    def table(tb: TableBox):
        cells = tb.cells
        nr = max(c.row + c.rspan for c in cells)
        nc = max(c.col + c.cspan for c in cells)
        cw = _sizes(cells, nc, lambda c: c.col, lambda c: c.cspan, lambda c: c.w)
        rh = _sizes(cells, nr, lambda c: c.row, lambda c: c.rspan, lambda c: c.h)
        known = sum(x for x in cw if x)
        cw = [x if x else max((frame_w / PT - known) / max(cw.count(None), 1), 1) for x in cw]
        scale = min(1.0, frame_w / (sum(cw) * PT))
        cw = [x * PT * scale for x in cw]
        # 한 줄이 한 쪽보다 높으면(영수증 사진을 크게 붙인 칸) 그리지 못하고 단순 미리보기로 떨어진다 → 쪽 높이 안으로 줄임 (2026-11-02 NoBrains)
        rh = [min((x or 0) * PT * scale, frame_h * 0.9) for x in rh]
        grid = [[""] * nc for _ in range(nr)]
        cmds = [("FONTNAME", (0, 0), (-1, -1), "Nanum")]
        grow = set()
        for c in cells:
            full_w = sum(cw[c.col:c.col + c.cspan])
            # 칸 안쪽 여백: 표 기본값을 쓰는 칸은 값이 비정상으로 크게 읽힐 수 있어 칸 너비의 1/6로 묶는다
            pl, pr, pt, pb = (min(v * PT * scale, full_w / 6) for v in c.pad)
            inner_w = full_w - pl - pr
            inner_h = max(min(sum(rh[c.row:c.row + c.rspan]), frame_h * 0.85) - pt - pb, 20)  # 병합 칸도 한 쪽 안
            n_pic = max(sum(not isinstance(x, Para) for x in c.items), 1)  # 한 칸에 사진 여러 장(영수증 2장)이면 높이를 나눔
            items = [para(x) if isinstance(x, Para) else picture(x, inner_w, inner_h / n_pic) for x in c.items]
            if c.rspan == 1:  # 내용이 원래 칸보다 길면(학생이 길게 씀) 그 줄은 늘린다
                need = sum(f.wrap(inner_w, 10000)[1] for f in items) + pt + pb
                if need > rh[c.row] + 1:
                    grow.add(c.row)
            grid[c.row][c.col] = items
            a, b = (c.col, c.row), (c.col + c.cspan - 1, c.row + c.rspan - 1)
            if c.rspan > 1 or c.cspan > 1:
                cmds.append(("SPAN", a, b))
            cmds += [("VALIGN", a, b, c.valign), ("LEFTPADDING", a, b, pl), ("RIGHTPADDING", a, b, pr),
                     ("TOPPADDING", a, b, pt), ("BOTTOMPADDING", a, b, pb)]
            sides, bg = st.border_fills[c.bf - 1] if 0 < c.bf <= len(st.border_fills) else ([(1, 1, 0)] * 4, None)
            if bg:
                cmds.append(("BACKGROUND", a, b, colors.HexColor(bg)))
            for (kind, wcode, color), cmd in zip(sides, ("LINEBEFORE", "LINEAFTER", "LINEABOVE", "LINEBELOW")):
                if kind:  # 0 = 선 없음
                    cmds.append((cmd, a, b, LINE_MM[min(wcode, 15)] * mm, colors.HexColor(_rgb(color))))
        heights = [None if i in grow else h for i, h in enumerate(rh)]
        t = Table(grid, colWidths=cw, rowHeights=heights)
        t.setStyle(TableStyle(cmds))
        return t

    class Doc(SimpleDocTemplate):
        chrome = Chrome()

        def afterPage(self):  # 쪽마다 그 구역의 머리말·꼬리말 그림
            c = self.canv
            for pics, top in ((self.chrome.head, True), (self.chrome.foot, False)):
                for pc in pics:
                    w, h = pc.w * PT, pc.h * PT
                    if not w or not h:
                        continue
                    x = W - mr - w if pc.x * PT > frame_w / 2 else ml
                    y = H - mt - h if top else mb
                    try:
                        c.drawImage(ImageReader(io.BytesIO(pc.data)), x, y, w, h, mask="auto")
                    except Exception:
                        pass

    class SetChrome(Flowable):  # 구역이 바뀌는 곳에서 머리말·꼬리말 그림을 바꾼다
        def __init__(self, ch):
            super().__init__()
            self.ch, self.width, self.height = ch, 0, 0

        def draw(self):
            Doc.chrome = self.ch

    story = []
    for item in flow:
        if isinstance(item, Chrome):
            story.append(SetChrome(item))
        elif isinstance(item, Pic):
            story.append(picture(item.data, min(item.w * PT or frame_w, frame_w), min(item.h * PT or H / 2, H - mt - mb - mh - mf)))
        elif isinstance(item, PageBreak):
            if any(isinstance(x, RLBreak) for x in story[-2:]) and not any(isinstance(x, (Table, Paragraph, Image)) for x in story[-2:]):
                continue  # 구역 나눔 + 문단의 쪽 나눔이 겹치면 빈 쪽이 생긴다
            story.append(RLBreak())
        elif isinstance(item, Para):
            story.append(para(item))
        elif isinstance(item, TableBox) and item.cells:
            story.append(table(item))
        elif isinstance(item, bytes):
            story.append(picture(item, frame_w, H / 2))
    while story and isinstance(story[-1], (RLBreak, Spacer, SetChrome)):
        story.pop()
    buf = io.BytesIO()
    Doc(buf, pagesize=(W, H), leftMargin=ml, rightMargin=mr, topMargin=mt + mh, bottomMargin=mb + mf).build(story)
    return buf.getvalue()

