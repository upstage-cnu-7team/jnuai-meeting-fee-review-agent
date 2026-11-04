"""문서 읽기 계층: 형식 판별 → 형식별 리더 → 공통 `Document`."""
from __future__ import annotations

import io
import zipfile

from ..model import Document, Image, Page

MAX_BYTES = 100 * 1024 * 1024  # 네이버 대용량 첨부(36MB HWP, 사진이 BMP로 들어감)까지 읽는다. Upstage에는 slim 사본을 보낸다

_IMAGE_MAGIC = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif"}


class UnsupportedFormat(ValueError):
    pass


def sniff(data: bytes, filename: str = "") -> str:
    """내용(매직 바이트)을 먼저 보고, zip·OLE 안쪽 구조로 세부 형식을 가린다. 확장자는 보조로만 쓴다.

    → 'pdf' / 'hwp' / 'hwpx' / 'docx' / 'image' / 'unknown'
    """
    name = filename.lower()
    if data[:5] == b"%PDF-":
        return "pdf"
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":  # OLE 복합 문서: HWP 5.x 또는 옛 .doc
        import olefile

        try:
            with olefile.OleFileIO(io.BytesIO(data)) as ole:
                return "hwp" if ole.exists("FileHeader") and ole.exists("BodyText") else "unknown"
        except Exception:
            return "hwp" if name.endswith(".hwp") else "unknown"
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "mimetype" in names and z.read("mimetype").startswith(b"application/hwp+zip"):
                    return "hwpx"
                if any(n.startswith("Contents/section") for n in names):
                    return "hwpx"
                if "word/document.xml" in names:
                    return "docx"
        except zipfile.BadZipFile:
            return "unknown"
        return "unknown"
    for magic, _mime in _IMAGE_MAGIC.items():
        if data.startswith(magic):
            return "image"
    return "unknown"


def load(data: bytes, filename: str = "") -> Document:
    if len(data) > MAX_BYTES:
        raise UnsupportedFormat(f"{filename or '파일'}이(가) {MAX_BYTES // 1024 // 1024}MB를 넘습니다")
    kind = sniff(data, filename)
    if kind == "pdf":
        from .pdf import read_pdf

        return read_pdf(data, filename)
    if kind == "docx":
        from .docx import read_docx

        return read_docx(data, filename)
    if kind == "hwp":
        from .hwp import read_hwp

        return read_hwp(data, filename)
    if kind == "hwpx":
        from .hwpx import read_hwpx

        return read_hwpx(data, filename)
    if kind == "image":  # 사진으로 찍은 영수증 등 — OCR 범위 밖
        mime = next(m for magic, m in _IMAGE_MAGIC.items() if data.startswith(magic))
        doc = Document("image", filename, [Page(1, loose_images=[Image(data, mime)])])
        doc.warnings.append("이미지 파일: 글자를 읽으려면 OCR이 필요합니다")
        return doc
    raise UnsupportedFormat(f"{filename or '파일'}: 지원하지 않는 형식입니다 (HWP·HWPX·PDF·DOCX만)")
