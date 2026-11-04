"""DOCX 리더 (python-docx). 본문 순서대로 문단·표를 읽고, 쪽 나누기 위치로 쪽을 나눈다."""
from __future__ import annotations

import io

import docx
from docx.oxml.ns import qn

from ..model import Cell, Document, Image, Page, Table

_BLIP = "{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_EMBED = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"


def _images(el, part) -> list[Image]:
    out = []
    for blip in el.iter(_BLIP):
        rid = blip.get(_EMBED)
        try:
            img = part.related_parts[rid]
            out.append(Image(img.blob, img.content_type))
        except Exception:
            out.append(Image())
    return out


def _text(el) -> str:
    """문단(들)의 텍스트. 문단 사이와 줄바꿈(w:br)은 줄바꿈으로."""
    lines = []
    for p in el.iter(qn("w:p")):
        buf = []
        for node in p.iter():
            if node.tag == qn("w:t"):
                buf.append(node.text or "")
            elif node.tag == qn("w:tab"):
                buf.append("\t")
            elif node.tag == qn("w:br") and node.get(qn("w:type")) != "page":
                buf.append("\n")
        lines.append("".join(buf))
    return "\n".join(lines)


def _page_break(p) -> tuple[bool, bool]:
    """(문단 앞 쪽 나누기, 문단 뒤 쪽 나누기)."""
    before = p.find(f"{qn('w:pPr')}/{qn('w:pageBreakBefore')}") is not None
    after = any(br.get(qn("w:type")) == "page" for br in p.iter(qn("w:br")))
    after = after or p.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is not None
    return before, after


def _table(tbl, part) -> Table:
    rows = []
    for tr in tbl.iterchildren(qn("w:tr")):
        cells = []
        for tc in tr.iterchildren(qn("w:tc")):
            vm = tc.find(f"{qn('w:tcPr')}/{qn('w:vMerge')}")
            if vm is not None and vm.get(qn("w:val")) != "restart":
                continue  # 세로 병합의 이어진 칸
            cells.append(Cell(_text(tc), _images(tc, part)))
        if cells:
            rows.append(cells)
    return Table(rows)


def read_docx(data: bytes, filename: str = "") -> Document:
    d = docx.Document(io.BytesIO(data))
    part = d.part
    pages = [Page(1)]
    body: list[str] = []

    def new_page():
        nonlocal body
        pages[-1].body = "\n".join(body)
        body = []
        pages.append(Page(len(pages) + 1))

    for el in d.element.body.iterchildren():
        if el.tag == qn("w:p"):
            before, after = _page_break(el)
            if before and (body or pages[-1].tables):
                new_page()
            body.extend(_text(el).splitlines())
            pages[-1].loose_images.extend(_images(el, part))
            if after:
                new_page()
        elif el.tag == qn("w:tbl"):
            pages[-1].tables.append(_table(el, part))
    pages[-1].body = "\n".join(body)
    if len(pages) > 1 and not pages[-1].text and not pages[-1].image_count:
        pages.pop()  # 마지막 쪽 나누기 뒤 빈 쪽
    return Document("docx", filename, pages)
