"""첨부를 쪽 이미지(150dpi PNG)로 바꾼다. 담당자가 원본을 서비스 화면에서 바로 보게 하려는 것이다.

- PDF·스캔: 원본을 그대로 그린다 (pypdfium2).
- 이미지: PNG로 바꾼다 (A4 폭 1240px에 맞춤).
- HWP: hwp_render.py가 HWP 안의 칸 병합·크기·배경·글자 모양으로 원본과 같은 모양을 그린다.
- HWPX·DOCX(그리고 HWP 원본 모양 그리기가 실패한 경우): LibreOffice가 HWP 5.0·HWPX를 못 읽고 DOCX도 한글 글꼴이 빠져서(2026-10-31 시험),
  파이썬 문서 리더가 읽은 표·칸·그림을 나눔고딕으로 다시 그린 '미리보기'를 만든다. 원래 모양과 똑같지는 않다.
"""
from __future__ import annotations

import io

import pypdfium2 as pdfium
from PIL import Image as PILImage

from minutes_review.model import Document

from ..config import BACKEND

DPI = 150
A4_W = 1240
FONT_DIR = BACKEND / "assets" / "fonts"
_fonts_ready = False


def _pdf_pages(data: bytes, max_pages: int = 30) -> list[bytes]:
    out = []
    doc = pdfium.PdfDocument(data)
    for i in range(min(len(doc), max_pages)):
        im = doc[i].render(scale=DPI / 72).to_pil().convert("RGB")
        out.append(_png(im))
    return out


def _png(im: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _image_page(data: bytes) -> list[bytes]:
    im = PILImage.open(io.BytesIO(data))
    im = im.convert("RGB")
    if im.width > A4_W:
        im = im.resize((A4_W, round(im.height * A4_W / im.width)))
    return [_png(im)]


def _fonts():
    global _fonts_ready
    if not _fonts_ready:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont("Nanum", str(FONT_DIR / "NanumGothic-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("NanumB", str(FONT_DIR / "NanumGothic-Bold.ttf")))
        _fonts_ready = True


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def document_to_pdf(doc: Document) -> bytes:
    """Document(쪽 → 본문·표·그림) → 미리보기 PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _fonts()
    body = ParagraphStyle("b", fontName="Nanum", fontSize=9, leading=12)
    note = ParagraphStyle("n", fontName="Nanum", fontSize=7, leading=9, textColor=colors.grey)
    width = A4[0] - 30 * mm

    def img(im, max_w):
        if not im.data:
            return Paragraph("[그림]", note)
        try:
            pil = PILImage.open(io.BytesIO(im.data))
            w, h = pil.size
        except Exception:
            return Paragraph("[그림]", note)
        scale = min(max_w / w, 80 * mm / h, 1.0 if w > max_w else max_w / w)
        return Image(io.BytesIO(im.data), width=w * scale, height=h * scale)

    story = [Paragraph(f"미리보기 ({doc.kind.upper()}): 원본 모양과 다를 수 있습니다. 정확한 모양은 원본 다운로드로 확인하세요.", note), Spacer(1, 3 * mm)]
    for pi, page in enumerate(doc.pages):
        if pi:
            story.append(PageBreak())
        for ln in page.body_lines:
            story.append(Paragraph(_esc(ln), body))
        for t in page.tables:
            ncol = max(len(r) for r in t.rows) if t.rows else 1
            colw = width / ncol
            data = []
            for r in t.rows:
                row = []
                for c in r:
                    parts = [Paragraph(_esc(c.text), body)] if c.text else []
                    parts += [img(im, colw - 4) for im in c.images]
                    row.append(parts or "")
                row += [""] * (ncol - len(r))
                data.append(row)
            if data:
                tbl = Table(data, colWidths=[colw] * ncol)
                tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                         ("FONTNAME", (0, 0), (-1, -1), "Nanum")]))
                story += [tbl, Spacer(1, 3 * mm)]
        for im in page.loose_images:
            story.append(img(im, width))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=15 * mm).build(story)
    return buf.getvalue()


def render_pages(data: bytes, fmt: str, doc: Document | None) -> list[bytes]:
    """→ 쪽별 PNG 바이트. 만들 수 없으면 빈 목록 (화면은 '미리보기를 만들 수 없습니다 + 원본 다운로드')."""
    try:
        if fmt in ("pdf", "scan"):
            return _pdf_pages(data)
        if fmt == "image":
            return _image_page(data)
        if fmt == "hwp":  # 원본 모양(병합·크기·배경·글자색)으로. 안 되면 아래 단순 미리보기
            try:
                from .hwp_render import render_pdf

                from .slim import shrink_image

                return _pdf_pages(render_pdf(data, shrink=shrink_image if len(data) > 5_000_000 else None))
            except Exception:
                pass
        if fmt in ("hwp", "hwpx", "docx") and doc is not None:
            return _pdf_pages(document_to_pdf(doc))
    except Exception:
        return []
    return []


def png_size(png: bytes) -> tuple[int, int]:
    return PILImage.open(io.BytesIO(png)).size
