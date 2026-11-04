"""테스트 샘플용 최소 HWP 5.x / HWPX 작성기.

한글 프로그램이 만든 파일과 똑같지는 않다: 글자 모양·문단 모양 같은 DocInfo 서식 레코드를 넣지 않으므로
한글에서 열면 서식이 깨질 수 있다. 대신 리더(minutes_review.extract)가 읽는 구조 — OLE 복합 문서, 압축된
BodyText 레코드(문단·표·칸·그림), DocInfo BIN_DATA, BinData 스트림 — 는 공개 명세대로 쓴다.
실제 한글 파일 읽기는 실제 빈 양식으로 따로 확인했다 (README).
"""
from __future__ import annotations

import io
import struct
import zipfile
import zlib
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

# ───────────────────────────── 공통 표 모델 ─────────────────────────────


@dataclass
class GCell:
    text: str = ""
    images: list[bytes] = field(default_factory=list)  # PNG
    cs: int = 1
    rs: int = 1


@dataclass
class GTable:
    cols: int
    rows: list[list[GCell]]  # 행마다 실제로 있는 칸만 (병합으로 덮인 자리는 생략)

    def placed(self):
        """(행, 열, 칸) — 병합으로 덮인 자리를 건너뛰며 열 주소를 매긴다."""
        taken: set[tuple[int, int]] = set()
        out = []
        for r, row in enumerate(self.rows):
            c = 0
            for cell in row:
                while (r, c) in taken:
                    c += 1
                out.append((r, c, cell))
                for dr in range(cell.rs):
                    for dc in range(cell.cs):
                        taken.add((r + dr, c + dc))
                c += cell.cs
        return out


# 문서 = 쪽 목록, 쪽 = 블록 목록 (str 문단 또는 GTable)
Doc = list[list]


# ───────────────────────────── OLE(CFB) 작성 ─────────────────────────────
FREE, END, FATSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD
NOSTREAM = 0xFFFFFFFF


def _cfb_key(name: str):
    return (len(name), name.upper())


def write_cfb(streams: dict[str, bytes]) -> bytes:
    """streams: {'FileHeader': ..., 'BodyText/Section0': ...} → CFB v3 (512바이트 섹터) 바이트."""
    # 디렉터리 항목: 0 = Root, 그다음 저장소·스트림
    entries = [{"name": "Root Entry", "type": 5, "children": [], "data": b""}]
    storages: dict[str, int] = {}
    for path in sorted(streams):
        parts = path.split("/")
        parent = 0
        for depth, part in enumerate(parts[:-1]):
            sp = "/".join(parts[: depth + 1])
            if sp not in storages:
                storages[sp] = len(entries)
                entries.append({"name": part, "type": 1, "children": [], "data": b""})
                entries[parent]["children"].append(storages[sp])
            parent = storages[sp]
        idx = len(entries)
        entries.append({"name": parts[-1], "type": 2, "children": [], "data": streams[path]})
        entries[parent]["children"].append(idx)

    # 형제는 이름 순 오른쪽 사슬로 (모두 검정 — 리더는 색을 검사하지 않음)
    for e in entries:
        e.update(left=NOSTREAM, right=NOSTREAM, child=NOSTREAM)
    for e in entries:
        kids = sorted(e["children"], key=lambda i: _cfb_key(entries[i]["name"]))
        if kids:
            e["child"] = kids[0]
            for a, b in zip(kids, kids[1:]):
                entries[a]["right"] = b

    # 작은 스트림(4096바이트 미만)은 미니 스트림에
    mini = bytearray()
    minifat: list[int] = []
    big: list[tuple[int, bytes]] = []
    for i, e in enumerate(entries):
        if e["type"] != 2:
            continue
        d = e["data"]
        if len(d) < 4096:
            start = len(mini) // 64
            n = max(1, -(-len(d) // 64)) if d else 0
            e["start"] = start if d else END
            mini += d + b"\0" * (n * 64 - len(d))
            for k in range(n):
                minifat.append(start + k + 1 if k < n - 1 else END)
        else:
            big.append((i, d))

    def nsec(n_bytes):
        return -(-n_bytes // 512)

    n_dir = nsec(len(entries) * 128)
    n_minifat = nsec(len(minifat) * 4)
    n_mini = nsec(len(mini))
    n_big = sum(nsec(len(d)) for _i, d in big)
    n_fat = 1
    while n_fat * 128 < n_fat + n_dir + n_minifat + n_mini + n_big:
        n_fat += 1

    fat = [FATSECT] * n_fat
    sectors: list[bytes] = []

    def chain(data: bytes) -> int:
        start = n_fat + len(sectors)
        n = nsec(len(data))
        for k in range(n):
            sectors.append(data[k * 512 : (k + 1) * 512].ljust(512, b"\0"))
            fat.append(start + k + 1 if k < n - 1 else END)
        return start if n else END

    dir_start_placeholder = len(sectors)
    sectors.extend([b""] * n_dir)  # 디렉터리는 마지막에 채움
    fat.extend([n_fat + dir_start_placeholder + k + 1 if k < n_dir - 1 else END for k in range(n_dir)])
    minifat_start = chain(b"".join(struct.pack("<I", x) for x in minifat)) if minifat else END
    entries[0]["start"] = chain(bytes(mini)) if mini else END
    entries[0]["data"] = bytes(mini)
    for i, d in big:
        entries[i]["start"] = chain(d)
    fat += [FREE] * (n_fat * 128 - len(fat))

    dirbuf = bytearray()
    for e in entries:
        name = e["name"].encode("utf-16-le") + b"\0\0"
        dirbuf += name.ljust(64, b"\0")
        dirbuf += struct.pack("<HBB3I", len(name), e["type"], 1, e["left"], e["right"], e["child"])
        dirbuf += b"\0" * 16 + b"\0" * 4 + b"\0" * 16
        size = len(e["data"]) if e["type"] in (2, 5) else 0
        dirbuf += struct.pack("<IQ", e.get("start", END) if e["type"] != 1 else 0, size)
    dirbuf = bytes(dirbuf).ljust(n_dir * 512, b"\0")
    # 빈 디렉터리 자리는 NOSTREAM 링크가 필요하지만, 항목 수만큼만 읽히므로 0으로 채워도 olefile은 '빈 항목'으로 본다
    for k in range(n_dir):
        sectors[dir_start_placeholder + k] = dirbuf[k * 512 : (k + 1) * 512]

    header = bytearray(512)
    header[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHHHH", header, 24, 0x3E, 3, 0xFFFE, 9, 6)
    struct.pack_into("<IIIIIIIII", header, 40, 0, n_fat, n_fat + dir_start_placeholder, 0, 4096,
                     minifat_start, n_minifat if minifat else 0, END, 0)
    for k in range(109):
        struct.pack_into("<I", header, 76 + 4 * k, k if k < n_fat else FREE)
    fatbytes = b"".join(struct.pack("<I", x) for x in fat)
    return bytes(header) + fatbytes + b"".join(sectors)


# ───────────────────────────── HWP 5.x ─────────────────────────────
PARA_HEADER, PARA_TEXT, CTRL_HEADER, LIST_HEADER, TABLE, SHAPE_COMPONENT, SHAPE_PICTURE = 66, 67, 71, 72, 77, 76, 85
BIN_DATA = 18


def _rec(tag: int, level: int, body: bytes) -> bytes:
    if len(body) >= 0xFFF:
        return struct.pack("<II", tag | (level << 10) | (0xFFF << 20), len(body)) + body
    return struct.pack("<I", tag | (level << 10) | (len(body) << 20)) + body


def _ctrl_chars(chid: bytes) -> bytes:
    """확장 컨트롤 문자(11) 8단위: 문자, 컨트롤 ID 4바이트, 예약, 문자."""
    return struct.pack("<H", 11) + chid + b"\0" * 8 + struct.pack("<H", 11)


def _para(level: int, text: str, page_break=False, ctrls: list[bytes] = ()) -> bytes:
    body = b"".join(_ctrl_chars(c) for c in ctrls) + text.encode("utf-16-le") + struct.pack("<H", 13)
    nchars = len(body) // 2
    head = struct.pack("<IIHBB", nchars, 0x800 if ctrls else 0, 0, 0, 0x04 if page_break else 0) + b"\0" * 12
    return _rec(PARA_HEADER, level, head) + _rec(PARA_TEXT, level + 1, body)


def write_hwp(doc: Doc) -> bytes:
    bins: list[bytes] = []
    out = bytearray()

    def picture(level: int, png: bytes) -> bytes:
        bins.append(png)
        bid = len(bins)
        pic = bytearray(12 + 32 + 16 + 8 + 3 + 2 + 32)
        struct.pack_into("<H", pic, 71, bid)
        return (_rec(CTRL_HEADER, level, b" osg" + b"\0" * 40) + _rec(SHAPE_COMPONENT, level + 1, b"$pic$pic" + b"\0" * 192)
                + _rec(SHAPE_PICTURE, level + 2, bytes(pic)))

    def cell_paras(level: int, cell: GCell) -> bytes:
        buf = bytearray()
        lines = cell.text.split("\n") if cell.text else [""]
        for k, ln in enumerate(lines):
            last = k == len(lines) - 1
            ctrls = [b" osg"] * len(cell.images) if last else []
            buf += _para(level, ln, ctrls=ctrls)
            if last:
                for png in cell.images:
                    buf += picture(level + 1, png)
        return bytes(buf)

    for pi, page in enumerate(doc):
        for bi, block in enumerate(page):
            brk = pi > 0 and bi == 0
            if isinstance(block, str):
                out += _para(0, block, page_break=brk)
                continue
            t: GTable = block
            out += _para(0, "", page_break=brk, ctrls=[b" lbt"])
            out += _rec(CTRL_HEADER, 1, b" lbt" + b"\0" * 40)
            nrows = len(t.rows)
            out += _rec(TABLE, 2, struct.pack("<IHHH4H", 0, nrows, t.cols, 0, 0, 0, 0, 0) + b"\0\0" * nrows + b"\0\0" + b"\0\0")
            for r, c, cell in t.placed():
                nparas = len(cell.text.split("\n")) if cell.text else 1
                lh = struct.pack("<HHI", nparas, 0, 0) + struct.pack("<HHHHII4HHI", c, r, cell.cs, cell.rs, 8000, 1000, 0, 0, 0, 0, 1, 0)
                out += _rec(LIST_HEADER, 2, lh)
                out += cell_paras(2, cell)

    docinfo = bytearray()
    for i, _png in enumerate(bins, 1):
        ext = "png".encode("utf-16-le")
        docinfo += _rec(BIN_DATA, 0, struct.pack("<HHH", 1, i, 3) + ext)

    def z(b: bytes) -> bytes:
        c = zlib.compressobj(9, zlib.DEFLATED, -15)
        return c.compress(b) + c.flush()

    header = b"HWP Document File".ljust(32, b"\0") + struct.pack("<II", 0x05010001, 1)
    header = header.ljust(256, b"\0")
    # 문서 요약 정보: 빈 속성 집합 (pyhwp 등 다른 리더가 이 스트림을 요구함)
    fmtid = bytes.fromhex("e0859ff2f94f6810ab9108002b27b3d9")
    summary = struct.pack("<HHI16sI", 0xFFFE, 0, 0x00020006, b"\0" * 16, 1) + fmtid + struct.pack("<I", 48) + struct.pack("<II", 8, 0)
    streams = {"\x05HwpSummaryInformation": summary, "FileHeader": header, "DocInfo": z(bytes(docinfo)), "BodyText/Section0": z(bytes(out))}
    for i, png in enumerate(bins, 1):
        streams[f"BinData/BIN{i:04X}.png"] = z(png)
    return write_cfb(streams)


# ───────────────────────────── HWPX ─────────────────────────────
NS = ('xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
      'xmlns:hc="http://www.hancom.co.kr/hwpml/2011/core"')


def write_hwpx(doc: Doc) -> bytes:
    bins: list[bytes] = []

    def pic(png: bytes) -> str:
        bins.append(png)
        return f'<hp:pic id="{len(bins)}"><hc:img binaryItemIDRef="image{len(bins)}"/></hp:pic>'

    def para(text: str, page_break=False, inner: str = "") -> str:
        runs = "".join(f"<hp:run><hp:t>{escape(ln)}</hp:t></hp:run>" for ln in [text] if text)
        return f'<hp:p pageBreak="{1 if page_break else 0}">{runs}{inner}</hp:p>'

    def table(t: GTable) -> str:
        rows: dict[int, list[str]] = {}
        for r, c, cell in t.placed():
            lines = cell.text.split("\n") if cell.text else [""]
            ps = "".join(para(ln, inner=("<hp:run>" + "".join(pic(p) for p in cell.images) + "</hp:run>") if k == len(lines) - 1 and cell.images else "")
                         for k, ln in enumerate(lines))
            rows.setdefault(r, []).append(f'<hp:tc><hp:subList>{ps}</hp:subList><hp:cellAddr colAddr="{c}" rowAddr="{r}"/>'
                                          f'<hp:cellSpan colSpan="{cell.cs}" rowSpan="{cell.rs}"/></hp:tc>')
        trs = "".join(f"<hp:tr>{''.join(rows[r])}</hp:tr>" for r in sorted(rows))
        return f'<hp:tbl rowCnt="{len(t.rows)}" colCnt="{t.cols}">{trs}</hp:tbl>'

    body = []
    for pi, page in enumerate(doc):
        for bi, block in enumerate(page):
            brk = pi > 0 and bi == 0
            if isinstance(block, str):
                body.append(para(block, brk))
            else:
                body.append(para("", brk, inner=f"<hp:run>{table(block)}</hp:run>"))
    sec = f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {NS}>{"".join(body)}</hs:sec>'
    items = "".join(f'<opf:item id="image{i}" href="BinData/image{i}.png" media-type="image/png"/>' for i in range(1, len(bins) + 1))
    hpf = ('<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
           f'<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>{items}</opf:manifest></opf:package>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/hwp+zip")
        z.writestr("Contents/content.hpf", hpf, zipfile.ZIP_DEFLATED)
        z.writestr("Contents/section0.xml", sec, zipfile.ZIP_DEFLATED)
        for i, png in enumerate(bins, 1):
            z.writestr(f"BinData/image{i}.png", png)
    return buf.getvalue()
