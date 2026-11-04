"""Upstage에 보낼 가벼운 사본: 큰 파일은 안에 붙은 사진만 줄여서 보낸다 (이슈 #11).

학생이 휴대폰 사진(영수증·회의 사진)을 원본 크기로 붙이면 회의록 파일이 수십 MB가 된다.
Upstage 정보 추출은 파일 50MB·100쪽까지이고, base64로 보내므로 실제로는 더 작아야 한다.

- 판정(칸 안 그림·양식 대조)·미리보기·보관은 원본 그대로 쓴다. 이 사본은 Upstage 호출에만 쓴다.
- HWP는 PDF로 바꾸지 않고 BinData 그림만 줄여 HWP로 다시 쓴다. 다시 쓴 파일을 리더로 읽어 글자·표가 원본과 같을 때만 쓴다.
- HWPX·DOCX는 zip 안 그림을 줄인다. 사진 파일은 그대로 줄인다. PDF는 그대로 보낸다.
- 기준 크기 이하 파일은 바이트 하나 바꾸지 않는다 (Upstage 캐시 키·회귀 fixture 유지).
- 무엇이든 실패하면 원본을 보낸다.
"""
from __future__ import annotations

import io
import logging
import zipfile
import zlib

import olefile
from PIL import Image as PILImage, ImageOps

from minutes_review.extract import load, sniff

from ..config import get_settings

log = logging.getLogger("slim")

IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff")


def shrink_image(raw: bytes) -> bytes:
    """긴 변을 image_max_px로 줄이고 같은 형식으로 다시 저장한다. 작은 그림(서명 등)·줄일 필요 없는 그림·더 커지면 원본."""
    s = get_settings()
    if len(raw) < s.slim_image_min_bytes:
        return raw
    try:
        im = PILImage.open(io.BytesIO(raw))
        fmt = im.format
        if fmt not in ("JPEG", "PNG", "BMP", "GIF", "TIFF"):
            return raw
        im = ImageOps.exif_transpose(im)  # 휴대폰 사진의 회전 정보를 픽셀에 반영 (다시 저장하면 EXIF가 빠지므로)
        if max(im.size) > s.image_max_px:
            im.thumbnail((s.image_max_px, s.image_max_px), PILImage.LANCZOS)
        buf = io.BytesIO()
        if fmt == "JPEG":
            im.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
        else:
            im.save(buf, fmt, **({"optimize": True} if fmt == "PNG" else {}))
        out = buf.getvalue()
    except Exception:
        return raw
    return out if len(out) < len(raw) else raw


def _same_content(a: bytes, b: bytes) -> bool:
    """다시 쓴 파일이 원본과 같은 글자·표를 읽히는가 (그림 바이트만 달라야 한다)."""
    try:
        da, db = load(a, ""), load(b, "")
    except Exception:
        return False
    return [(p.text, [t.texts() for t in p.tables], p.image_count) for p in da.pages] == \
           [(p.text, [t.texts() for t in p.tables], p.image_count) for p in db.pages]


def _slim_hwp(data: bytes) -> bytes:
    from tools.hwpkit import write_cfb

    streams: dict[str, bytes] = {}
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        for path in ole.listdir(streams=True, storages=False):
            name = "/".join(path)
            raw = ole.openstream(path).read()
            if path[0] == "BinData" and name.lower().endswith(IMAGE_EXT):
                try:  # BinData는 보통 raw deflate로 압축돼 있다. 풀리면 다시 압축해 넣는다
                    plain, packed = zlib.decompress(raw, -15), True
                except zlib.error:
                    plain, packed = raw, False
                small = shrink_image(plain)
                if small is not plain:
                    c = zlib.compressobj(9, zlib.DEFLATED, -15)
                    raw = c.compress(small) + c.flush() if packed else small
            streams[name] = raw
    return write_cfb(streams)


def _slim_zip(data: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as dst:
        for info in src.infolist():  # 순서·압축 방식 유지 (HWPX는 mimetype이 맨 앞·무압축이어야 한다)
            body = src.read(info)
            if info.filename.lower().endswith(IMAGE_EXT):
                body = shrink_image(body)
            dst.writestr(info, body, compress_type=info.compress_type)
    return buf.getvalue()


def for_upstage(data: bytes, filename: str = "") -> bytes:
    """Upstage 정보 추출에 보낼 바이트. 기준 크기 이하이거나 줄이지 못하면 원본 그대로."""
    limit = get_settings().slim_upload_bytes
    if len(data) <= limit:
        return data
    fmt = sniff(data, filename)
    try:
        if fmt == "image":
            out = shrink_image(data)
        elif fmt == "hwp":
            out = _slim_hwp(data)
        elif fmt in ("hwpx", "docx"):
            out = _slim_zip(data)
        else:
            out = data
        if out is not data and fmt != "image" and not _same_content(data, out):
            log.warning("slim %s: 다시 쓴 파일 내용이 원본과 달라 원본을 보냄", fmt)
            out = data
    except Exception as e:
        log.warning("slim %s 실패, 원본을 보냄 (%s)", fmt, type(e).__name__)
        out = data
    if len(out) < len(data):
        log.info("slim %s: %.1fMB → %.1fMB", fmt, len(data) / 1e6, len(out) / 1e6)
    return out if len(out) < len(data) else data


def for_extract(data: bytes, filename: str = "") -> bytes:
    """Upstage 정보 추출에 실제로 보낼 바이트. 큰 HWP는 사진을 줄여 가며 원본 모양 PDF로 그려 보낸다.
    hwpkit으로 다시 쓴 HWP는 Upstage가 '지원하지 않는 형식'(400)으로 거절하고(2026-11-02 전자파),
    다시 쓰기는 7MB를 넘으면 실패한다(s_20261102_0014 23.8MB). 그래서 다시 쓰지 않고 바로 PDF로 그린다."""
    if len(data) <= get_settings().slim_upload_bytes or sniff(data, filename) != "hwp":
        return for_upstage(data, filename)
    try:
        from .hwp_render import render_pdf

        return render_pdf(data, shrink=shrink_image)
    except Exception as e:
        log.warning("큰 hwp→pdf 실패, 사진만 줄인 HWP를 보냄 (%s)", type(e).__name__)
        return for_upstage(data, filename)
