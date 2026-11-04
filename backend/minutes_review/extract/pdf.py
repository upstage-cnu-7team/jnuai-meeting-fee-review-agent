"""PDF 리더 (pdfplumber). 텍스트 PDF 기준이며, 글자가 없는 쪽은 스캔본으로 보고 OCR 필요로 표시한다."""
from __future__ import annotations

import io

import pdfplumber

from ..model import Cell, Document, Image, Page, Table


def _inside(obj: dict, bbox) -> bool:
    x0, top, x1, bottom = bbox
    cx, cy = (obj["x0"] + obj["x1"]) / 2, (obj["top"] + obj["bottom"]) / 2
    return x0 <= cx <= x1 and top <= cy <= bottom


def _image(page, img: dict) -> Image:
    """그림 영역을 PNG로 렌더링 (압축 방식과 무관하게 비전 판독에 쓸 수 있게)."""
    try:
        bbox = (max(img["x0"], 0), max(img["top"], 0), min(img["x1"], page.width), min(img["bottom"], page.height))
        # 원본 사진 해상도에 맞춰 그린다(110dpi로 고정하면 작게 붙인 영수증 사진이 뭉개져 날짜·금액을 잘못 읽음, 2026-11-04 AiBara)
        src_w = (img.get("srcsize") or (0, 0))[0]
        dpi = min(max(110, 72 * src_w / max(img["x1"] - img["x0"], 1)), 400)
        buf = io.BytesIO()
        page.crop(bbox).to_image(resolution=dpi).original.save(buf, "PNG")
        return Image(buf.getvalue(), "image/png")
    except Exception:  # 렌더링 실패해도 개수는 센다
        return Image()


def read_pdf(data: bytes, filename: str = "", max_pages: int = 60) -> Document:
    pages: list[Page] = []
    warnings: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        if len(pdf.pages) > max_pages:
            raise ValueError(f"{filename or '파일'}: {len(pdf.pages)}쪽으로 최대 {max_pages}쪽을 넘습니다")
        for i, p in enumerate(pdf.pages):
            try:
                found = p.find_tables()
            except Exception:  # 표 인식 실패 → 텍스트만으로 진행
                found = []
                warnings.append(f"{i + 1}쪽 표 인식 실패")
            images = list(p.images)
            used: set[int] = set()
            tables = []
            for t in found:
                rows = []
                texts = t.extract()  # 글자 중심점 기준으로 칸에 배정 (crop은 경계 글자가 옆 칸으로 샘)
                for row, row_text in zip(t.rows, texts):
                    cells = []
                    for bbox, text in zip(row.cells, row_text):
                        if bbox is None:  # 병합된 자리
                            continue
                        imgs = []
                        for k, img in enumerate(images):
                            if k not in used and _inside(img, bbox):
                                used.add(k)
                                imgs.append(_image(p, img))
                        cells.append(Cell(text or "", imgs))
                    if cells:
                        rows.append(cells)
                tables.append(Table(rows))
            boxes = [t.bbox for t in found]
            outside = p.filter(lambda o: not any(_inside(o, b) for b in boxes) if "x0" in o else True)
            body = outside.extract_text() or ""
            loose = [_image(p, img) for k, img in enumerate(images) if k not in used]
            pages.append(Page(i + 1, body, tables, loose))
    return Document("pdf", filename, pages, warnings)
