"""HWP 5.x(바이너리, OLE 복합 문서) 리더 — olefile로 BodyText 레코드를 직접 해석한다.

왜 직접 파싱하나 (README 'HWP 처리 방식 비교' 참고):
- pyhwp는 표를 잘 읽지만 AGPL-3.0이고 2020년 이후 갱신이 없으며 설치 시 의존성(six)이 빠져 있다.
- LibreOffice+H2Orestart는 1GB 넘는 설치와 Java가 필요해 서버 배포가 무겁다.
- Upstage Document Parse는 학생 개인정보가 담긴 서류를 외부로 보내야 하고 유료다.
필요한 것은 문단 텍스트, 표 칸(행·열), 칸 안 그림 개수뿐이라 레코드 몇 종류만 읽으면 된다.

참고: 한글과컴퓨터 'HWP 5.0 문서 파일 구조' 공개 문서. 레코드 = 32비트 머리(태그 10비트·수준 10비트·크기 12비트) + 본문.
"""
from __future__ import annotations

import io
import struct
import zlib

import olefile

from ..model import Cell, Document, Image, Page, Table

# 태그 번호 (HWPTAG_BEGIN = 0x10)
BIN_DATA = 0x10 + 2
BORDER_FILL = 0x10 + 4
PARA_HEADER = 0x10 + 50
PARA_TEXT = 0x10 + 51
CTRL_HEADER = 0x10 + 55
LIST_HEADER = 0x10 + 56
TABLE = 0x10 + 61
SHAPE_PICTURE = 0x10 + 69
SHAPE_COMPONENT = 0x10 + 60  # 개체 요소: 크기·뒤집기·회전각

CHID_TABLE = b" lbt"  # 'tbl ' (4바이트 컨트롤 ID가 리틀엔디언으로 저장됨)

# PARA_TEXT 안의 제어 문자: 1글자짜리, 나머지는 8글자(16바이트) 묶음
_CHAR_CTRL = {0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31}
_MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "bmp": "image/bmp"}


class HwpReadError(ValueError):
    pass


def records(data: bytes):
    """(태그, 수준, 본문) 순회."""
    pos, n = 0, len(data)
    while pos + 4 <= n:
        (head,) = struct.unpack_from("<I", data, pos)
        pos += 4
        tag, level, size = head & 0x3FF, (head >> 10) & 0x3FF, (head >> 20) & 0xFFF
        if size == 0xFFF:
            (size,) = struct.unpack_from("<I", data, pos)
            pos += 4
        yield tag, level, data[pos : pos + size]
        pos += size


def para_text(raw: bytes) -> str:
    out = []
    units = struct.unpack(f"<{len(raw) // 2}H", raw[: len(raw) // 2 * 2])
    i = 0
    while i < len(units):
        u = units[i]
        if u >= 32:
            out.append(chr(u))
            i += 1
        elif u in _CHAR_CTRL:
            out.append("\n" if u in (10, 13) else (" " if u in (30, 31) else ""))
            i += 1
        else:  # 인라인·확장 컨트롤 (탭=9 포함): 8단위 묶음
            if u == 9:
                out.append("\t")
            i += 8
    return "".join(out)


def _stream(ole: olefile.OleFileIO, name: str, compressed: bool) -> bytes:
    raw = ole.openstream(name).read()
    if not compressed:
        return raw
    try:
        return zlib.decompress(raw, -15)
    except zlib.error:
        return raw


def _bin_streams(ole, docinfo: bytes) -> dict[int, str]:
    """DocInfo의 BIN_DATA 순서(1부터) → BinData 스트림 이름."""
    out, idx = {}, 0
    for tag, _lvl, body in records(docinfo):
        if tag != BIN_DATA:
            continue
        idx += 1
        flags = struct.unpack_from("<H", body, 0)[0]
        if flags & 0xF in (1, 2) and len(body) >= 6:  # 내장·스토리지
            sid = struct.unpack_from("<H", body, 2)[0]
            ext = ""
            if flags & 0xF == 1 and len(body) >= 6:
                n = struct.unpack_from("<H", body, 4)[0]
                ext = body[6 : 6 + 2 * n].decode("utf-16-le", "ignore").lower()
            out[idx] = f"BinData/BIN{sid:04X}.{ext}" if ext else f"BinData/BIN{sid:04X}"
    return out


def _fill_images(docinfo: bytes) -> dict[int, int]:
    """DocInfo의 테두리/배경(BORDER_FILL) 순서(1부터) → 배경 그림의 bindata id.
    칸 배경을 '그림'으로 채운 경우다. 학생이 서명 그림을 칸 배경으로 넣는 일이 있다(2026-10-31 실제 제출본에서 확인)."""
    out, idx = {}, 0
    for tag, _lvl, body in records(docinfo):
        if tag != BORDER_FILL:
            continue
        idx += 1
        if len(body) < 36:
            continue
        ftype = struct.unpack_from("<I", body, 32)[0]
        off = 36 + (12 if ftype & 1 else 0)  # 색 채우기(배경색·무늬색·무늬) 다음에 그림 채우기
        if ftype & 2 and len(body) >= off + 6:
            out[idx] = struct.unpack_from("<H", body, off + 4)[0]  # 채우기 방식(1) + 밝기·명암·효과(3) 다음
    return out


def _bin_image(ole, bid: int, bins: dict[int, str], compressed: bool) -> Image:
    name = bins.get(bid)
    if not name or not ole.exists(name):
        return Image()
    try:
        return Image(_stream(ole, name, compressed), _MIME.get(name.rsplit(".", 1)[-1]))
    except Exception:
        return Image()


def shape_rotation(rec: bytes) -> int:
    """SHAPE_COMPONENT의 회전각(도). 그림 개체는 앞에 개체 ID가 한 번 더 붙는다."""
    off = 4 if rec[:4] == rec[4:8] else 0
    try:
        return struct.unpack_from("<h", rec, off + 4 + 4 + 4 + 2 + 2 + 16 + 4)[0]
    except struct.error:
        return 0


def _rotated(img: Image, deg: int) -> Image:
    """한글에서 그림을 돌려 놓았으면(학생이 거꾸로 찍힌 영수증을 180° 돌림) 바이트도 같은 방향으로 돌린다."""
    deg %= 360
    if not img.data or deg not in (90, 180, 270):
        return img
    try:
        from PIL import Image as PILImage

        im = PILImage.open(io.BytesIO(img.data))
        fmt = "PNG" if im.format == "PNG" else "JPEG"
        out = im.rotate(-deg, expand=True)  # 한글은 시계 방향, PIL은 반시계 방향
        buf = io.BytesIO()
        (out.convert("RGB") if fmt == "JPEG" else out).save(buf, fmt, quality=92)
        img.data = buf.getvalue()
    except Exception:
        pass
    return img


def _picture(ole, body: bytes, bins: dict[int, str], compressed: bool, rotation: int = 0) -> Image:
    # 그림 개체: 테두리(색·굵기·속성 12) + 사각형 좌표(32) + 자르기(16) + 안쪽 여백(8) + 밝기·명암·효과(3) → bindata id
    off = 12 + 32 + 16 + 8 + 3
    if len(body) < off + 2:
        return Image()
    return _rotated(_bin_image(ole, struct.unpack_from("<H", body, off)[0], bins, compressed), rotation)


class _TableCtx:
    def __init__(self, level: int):
        self.level = level
        self.cells: dict[tuple[int, int], Cell] = {}
        self.cur: Cell | None = None

    def table(self) -> Table:
        rows: dict[int, list[tuple[int, Cell]]] = {}
        for (r, c), cell in self.cells.items():
            rows.setdefault(r, []).append((c, cell))
        return Table([[cell for _c, cell in sorted(rows[r], key=lambda x: x[0])] for r in sorted(rows)])


def read_hwp(data: bytes, filename: str = "") -> Document:
    try:
        ole = olefile.OleFileIO(io.BytesIO(data))
    except Exception as e:
        raise HwpReadError(f"{filename or '파일'}: HWP(OLE) 형식이 아닙니다") from e
    with ole:
        if not ole.exists("FileHeader"):
            raise HwpReadError(f"{filename or '파일'}: HWP FileHeader가 없습니다")
        header = ole.openstream("FileHeader").read()
        if not header.startswith(b"HWP Document File"):
            raise HwpReadError(f"{filename or '파일'}: HWP 서명이 없습니다")
        props = struct.unpack_from("<I", header, 36)[0]
        compressed = bool(props & 1)
        if props & 2:
            raise HwpReadError(f"{filename or '파일'}: 암호가 걸린 HWP는 읽을 수 없습니다")
        if props & 4:
            raise HwpReadError(f"{filename or '파일'}: 배포용 HWP는 읽을 수 없습니다 (PDF로 저장해 제출 요청)")
        docinfo = _stream(ole, "DocInfo", compressed) if ole.exists("DocInfo") else b""
        bins = _bin_streams(ole, docinfo)
        fills = {k: v for k, v in _fill_images(docinfo).items() if v in bins}
        sections = sorted(
            ("/".join(p) for p in ole.listdir() if len(p) == 2 and p[0] == "BodyText"),
            key=lambda s: int(s.rsplit("Section", 1)[-1] or 0),
        )
        pages: list[Page] = []
        for sec in sections:
            _read_section(ole, _stream(ole, sec, compressed), bins, compressed, pages, fills)
    return Document("hwp", filename, pages or [Page(1)])


def _read_section(ole, data: bytes, bins, compressed: bool, pages: list[Page], fills: dict[int, int] | None = None) -> None:
    page = Page(len(pages) + 1)
    pages.append(page)
    body: list[str] = []
    stack: list[_TableCtx] = []
    rotation = 0  # 바로 앞 개체 요소의 회전각

    def flush_body():
        page.body = "\n".join(x for x in body)

    for tag, level, rec in records(data):
        while stack and level <= stack[-1].level:  # 표가 끝남
            page.tables.append(stack.pop().table())
        if tag == PARA_HEADER and level == 0 and len(rec) >= 12:
            split = rec[11]
            if split & 0x04 and (body or page.tables or page.loose_images):  # 쪽 나누기
                flush_body()
                page = Page(len(pages) + 1)
                pages.append(page)
                body = []
        elif tag == CTRL_HEADER and rec[:4] == CHID_TABLE:
            stack.append(_TableCtx(level))
        elif tag == LIST_HEADER and stack and level == stack[-1].level + 1 and len(rec) >= 12:
            col, row = struct.unpack_from("<HH", rec, 8)
            ctx = stack[-1]
            ctx.cur = ctx.cells.setdefault((row, col), Cell(""))
            if fills and len(rec) >= 34:  # 칸 배경 그림 (서명을 배경으로 넣은 경우)
                bf = struct.unpack_from("<H", rec, 32)[0]
                if bf in fills:
                    ctx.cur.images.append(_bin_image(ole, fills[bf], bins, compressed))
        elif tag == PARA_TEXT:
            text = para_text(rec)
            if stack and stack[-1].cur is not None:
                cell = stack[-1].cur
                cell.text = (cell.text + "\n" + text).strip() if cell.text else text.strip()
            else:
                body.extend(text.splitlines())
        elif tag == SHAPE_COMPONENT:
            rotation = shape_rotation(rec)
        elif tag == SHAPE_PICTURE:
            img = _picture(ole, rec, bins, compressed, rotation)
            rotation = 0
            if stack and stack[-1].cur is not None:
                stack[-1].cur.images.append(img)
            else:
                page.loose_images.append(img)
    while stack:
        page.tables.append(stack.pop().table())
    flush_body()
    for p in pages:  # Cell.__post_init__은 생성 때만 돌므로 누적 텍스트를 다시 정리
        for t in p.tables:
            for r in t.rows:
                for c in r:
                    c.__post_init__()
