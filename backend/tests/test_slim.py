"""대용량 제출(이슈 #11): 큰 파일은 사진만 줄인 사본을 Upstage에 보내고, 판정에 쓰는 글자·표·그림 수는 그대로여야 한다."""
from __future__ import annotations

import io
import random
import zipfile
import zlib
from pathlib import Path

import olefile
import pytest
from PIL import Image as PILImage

from app.config import get_settings
from app.review import pipeline, readers, slim
from minutes_review.extract import load, sniff
from tools.hwpkit import write_cfb

REAL_HWP = Path(__file__).resolve().parents[1] / "experiments" / "real_form" / "files" / "R09a_식비60분.hwp"


def big_photo(w=1200, h=1600, fmt="JPEG") -> bytes:
    """휴대폰 사진 대용: 잡음뿐이라 압축되지 않는 큰 사진 (테스트용 HWP 작성기 한도 7MB 안에서)."""
    im = PILImage.frombytes("RGB", (w, h), random.Random(0).randbytes(w * h * 3))
    buf = io.BytesIO()
    im.save(buf, fmt, **({"quality": 95} if fmt == "JPEG" else {}))
    return buf.getvalue()


def _inflate(raw: bytes) -> bytes:
    try:
        return zlib.decompress(raw, -15)
    except zlib.error:
        return raw


def with_big_receipt(data: bytes) -> bytes:
    """실제 양식 HWP의 영수증 칸 사진을 같은 형식의 큰 사진으로 바꾼다."""
    receipt = readers.receipt_image(load(data, "x.hwp"))
    streams = {}
    with olefile.OleFileIO(io.BytesIO(data)) as ole:
        for path in ole.listdir(streams=True, storages=False):
            streams["/".join(path)] = ole.openstream(path).read()
    target = next(n for n, raw in streams.items() if n.startswith("BinData/") and _inflate(raw) == receipt)
    photo = big_photo(fmt=PILImage.open(io.BytesIO(receipt)).format)
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    streams[target] = c.compress(photo) + c.flush()
    return write_cfb(streams)


@pytest.fixture
def small_limit(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "slim_upload_bytes", 1_000_000)
    monkeypatch.setattr(s, "image_max_px", 800)
    return s


def test_small_file_untouched():
    data = REAL_HWP.read_bytes()
    assert slim.for_upstage(data, REAL_HWP.name) is data  # 캐시 키·회귀 fixture가 바뀌지 않게


@pytest.mark.skipif(not REAL_HWP.exists(), reason="실제 양식 실험 파일 없음")
def test_big_hwp_slimmed_keeps_content(small_limit):
    big = with_big_receipt(REAL_HWP.read_bytes())
    assert len(big) > 1_000_000 and sniff(big, "x.hwp") == "hwp"

    out = slim.for_upstage(big, "x.hwp")

    assert len(out) < len(big) / 2
    assert sniff(out, "x.hwp") == "hwp"
    a, b = load(big, "x.hwp"), load(out, "x.hwp")
    assert [p.text for p in a.pages] == [p.text for p in b.pages]
    assert readers.local_marks(a) == readers.local_marks(b)  # 서명·영수증 칸 판정 그대로
    photo = readers.receipt_image(b)
    assert photo and max(PILImage.open(io.BytesIO(photo)).size) == small_limit.image_max_px



@pytest.mark.skipif(not REAL_HWP.exists(), reason="실제 양식 실험 파일 없음")
def test_big_hwp_goes_to_upstage_as_pdf(small_limit):
    """다시 쓴 HWP는 Upstage가 400으로 거절해(2026-11-02 전자파) 큰 HWP는 원본 모양 PDF로 보낸다. 작은 파일은 그대로."""
    big = with_big_receipt(REAL_HWP.read_bytes())
    out = slim.for_extract(big, "x.hwp")
    assert out.startswith(b"%PDF") and len(out) < len(big)
    small = REAL_HWP.read_bytes()
    assert slim.for_extract(small, "x.hwp") is small or len(small) > small_limit.slim_upload_bytes

def test_big_hwpx_slimmed(small_limit, tmp_path):
    from tools.minutes_samples import BASE, build
    from tools.hwpkit import write_hwpx

    doc = build(BASE)
    data = write_hwpx(doc)
    src = zipfile.ZipFile(io.BytesIO(data))
    img = next(n for n in src.namelist() if n.lower().endswith(".png"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for info in src.infolist():
            body = src.read(info)
            if info.filename == img:
                p = io.BytesIO()
                PILImage.open(io.BytesIO(big_photo())).save(p, "PNG")
                body = p.getvalue()
            z.writestr(info, body, compress_type=info.compress_type)
    big = buf.getvalue()

    out = slim.for_upstage(big, "x.hwpx")

    assert len(out) < len(big) / 2
    assert zipfile.ZipFile(io.BytesIO(out)).namelist()[0] == "mimetype"
    assert [p.text for p in load(big, "").pages] == [p.text for p in load(out, "").pages]


def test_big_photo_file_slimmed(small_limit):
    data = big_photo()
    out = slim.for_upstage(data, "receipt.jpg")
    assert max(PILImage.open(io.BytesIO(out)).size) == small_limit.image_max_px


def test_broken_rewrite_falls_back_to_original(small_limit, monkeypatch):
    big = with_big_receipt(REAL_HWP.read_bytes())
    monkeypatch.setattr(slim, "_slim_hwp", lambda d: b"\xd0\xcf\x11\xe0broken")
    assert slim.for_upstage(big, "x.hwp") is big


def test_small_images_untouched():
    buf = io.BytesIO()
    PILImage.new("RGB", (3000, 100), "white").save(buf, "PNG")  # 서명처럼 가볍지만 긴 그림
    assert slim.shrink_image(buf.getvalue()) is not None
    assert slim.shrink_image(buf.getvalue()) == buf.getvalue()


def test_extract_all_sends_slim_copy(small_limit, monkeypatch):
    big = with_big_receipt(REAL_HWP.read_bytes())
    sent = []
    monkeypatch.setattr(pipeline.upstage, "extract", lambda data, cache: sent.append(data) or {"receipt_total": 1, "merchant_name": "x"})
    pipeline.extract_all(big, load(big, "x.hwp"), cache=None, filename="x.hwp")
    assert sent and all(len(x) < len(big) / 2 for x in sent)  # 문서 전체 + 영수증 사진 재추출 모두 줄인 사본
