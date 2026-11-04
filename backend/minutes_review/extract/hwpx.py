"""HWPX 리더 (zip + OWPML XML). 한글 2022 이후 기본 저장 형식이라 같이 지원한다."""
from __future__ import annotations

import io
import posixpath
import re
import zipfile

from lxml import etree

from ..model import Cell, Document, Image, Page, Table

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
_MAX_XML = 30 * 1024 * 1024  # 압축 폭탄 방지


def _local(el) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _walk(el, stop=("tbl",)):
    """el 아래를 순서대로 돌되 stop 태그(중첩 표)의 하위는 건너뛴다."""
    for child in el:
        name = _local(child)
        yield child
        if name not in stop:
            yield from _walk(child, stop)


def _para_text(p) -> str:
    buf = []
    for node in _walk(p):
        name = _local(node)
        if name == "t":
            buf.append(node.text or "")
            for sub in node:  # <hp:t>앞<hp:tab/>뒤</hp:t> 형태
                if _local(sub) == "tab":
                    buf.append("\t")
                elif _local(sub) == "lineBreak":
                    buf.append("\n")
                buf.append(sub.tail or "")
        elif name == "lineBreak" and _local(node.getparent()) != "t":
            buf.append("\n")
    return "".join(buf)


class _Reader:
    def __init__(self, z: zipfile.ZipFile):
        self.z = z
        self.items: dict[str, tuple[str, str]] = {}  # id → (경로, mime)
        hpf = next((n for n in z.namelist() if n.lower().endswith("content.hpf")), None)
        if hpf:
            root = etree.fromstring(self._read(hpf), _PARSER)
            base = posixpath.dirname(hpf)
            for it in root.iter():
                if _local(it) == "item" and it.get("id") and it.get("href"):
                    href = it.get("href")
                    path = href if href in z.namelist() else posixpath.normpath(posixpath.join(base, href))
                    self.items[it.get("id")] = (path, it.get("media-type", ""))

    def _read(self, name: str) -> bytes:
        if self.z.getinfo(name).file_size > _MAX_XML:
            raise ValueError(f"{name}이(가) 너무 큽니다")
        return self.z.read(name)

    def image(self, pic) -> Image:
        ref = next((n.get("binaryItemIDRef") for n in pic.iter() if _local(n) == "img"), None)
        path, mime = self.items.get(ref or "", ("", ""))
        if not path or path not in self.z.namelist():
            return Image()
        return Image(self._read(path), mime or None)

    def pics(self, el) -> list[Image]:
        return [self.image(n) for n in _walk(el) if _local(n) == "pic"]

    def table(self, tbl) -> Table:
        rows = []
        for tr in tbl:
            if _local(tr) != "tr":
                continue
            cells = []
            for tc in tr:
                if _local(tc) != "tc":
                    continue
                paras = [n for n in tc.iter() if _local(n) == "p"]
                text = "\n".join(_para_text(p) for p in paras)
                imgs = [self.image(n) for n in tc.iter() if _local(n) == "pic"]
                cells.append(Cell(text, imgs))
            if cells:
                rows.append(cells)
        return Table(rows)


def read_hwpx(data: bytes, filename: str = "") -> Document:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        r = _Reader(z)
        names = sorted(
            (n for n in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n)),
            key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[-1]).group()),
        )
        if not names:
            raise ValueError(f"{filename or '파일'}: HWPX 본문(section)이 없습니다")
        pages: list[Page] = []
        for name in names:
            sec = etree.fromstring(r._read(name), _PARSER)
            page = Page(len(pages) + 1)
            pages.append(page)
            body: list[str] = []
            for p in sec:
                if _local(p) != "p":
                    continue
                if p.get("pageBreak") == "1" and (body or page.tables or page.loose_images):
                    page.body = "\n".join(body)
                    body = []
                    page = Page(len(pages) + 1)
                    pages.append(page)
                text = _para_text(p)
                if text:
                    body.extend(text.splitlines())
                page.loose_images.extend(r.pics(p))
                for node in _walk(p):
                    if _local(node) == "tbl":
                        page.tables.append(r.table(node))
            page.body = "\n".join(body)
    return Document("hwpx", filename, pages)
