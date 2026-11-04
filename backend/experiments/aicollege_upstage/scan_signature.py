"""스캔본(이미지 PDF)에서 서명 칸 잉크로 서명 여부를 판정한다.

칸 정보가 없으므로 Upstage OCR(model=ocr)의 글자 좌표로 칸을 찾는다.
- 참석자: '서명' 머리글과 같은 줄에 '이름'·'학번'이 있으면 참석자 표. 서명 열(머리글 x) × 각 참석자 이름 행(이름 단어 y).
- 결제자: '서명' 머리글과 같은 줄에 '이름'은 있고 '학번'은 없으면 결제자 표. 바로 아래 줄의 이름 행.
칸을 잘라 표 테두리(길게 이어진 진한 줄)를 지운 뒤 진한 픽셀 비율이 기준을 넘으면 서명 있음.
"""
from __future__ import annotations

import io
import statistics

import pypdfium2 as pdfium
from PIL import Image

DARK = 120  # 이보다 어두우면 잉크
INK_MIN = 0.006  # 칸 면적 대비 잉크 비율 기준 (16건 보정값, README 참고)


def _box(w):
    xs = [v["x"] for v in w["boundingBox"]["vertices"]]
    ys = [v["y"] for v in w["boundingBox"]["vertices"]]
    return min(xs), min(ys), max(xs), max(ys)


def _cy(w):
    b = _box(w)
    return (b[1] + b[3]) / 2


def _cx(w):
    b = _box(w)
    return (b[0] + b[2]) / 2


def _same_line(words, ref, tol=12):
    return [w for w in words if abs(_cy(w) - _cy(ref)) <= tol]


H_RUN = 40  # 가로로 이만큼(픽셀) 이어지면 가로 테두리
V_RUN = 0.8  # 세로로 칸 높이의 이 비율 이상 이어지면 세로 테두리


def _runs(seq, min_len):
    """True가 min_len 이상 이어진 구간들."""
    out, start = [], None
    for i, v in enumerate(list(seq) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def ink_ratio(im: Image.Image, box) -> float:
    """칸 안 잉크 비율. 가로·세로로 길게 이어진 진한 줄(표 테두리)은 뺀다.
    스캔이 기울면 테두리가 비스듬하고, 가로·세로 테두리가 모서리에서 붙어 한 덩어리가 된다(A17 스캔에서 확인).
    그래서 방향별로 '위아래(좌우) 1픽셀 흔들림을 허용한 긴 줄'을 찾아 지운다."""
    x0, y0, x1, y1 = (int(round(v)) for v in box)
    crop = im.crop((x0, y0, x1, y1)).convert("L")
    w, h = crop.size
    if w < 4 or h < 4:
        return 0.0
    px = crop.load()
    dark = [[px[x, y] < DARK for x in range(w)] for y in range(h)]
    line = [[False] * w for _ in range(h)]
    for y in range(h):  # 가로 테두리
        band = [any(dark[yy][x] for yy in range(max(0, y - 1), min(h, y + 2))) for x in range(w)]
        for a, b in _runs(band, min(H_RUN, int(0.5 * w))):
            for x in range(a, b):
                line[y][x] = True
    for x in range(w):  # 세로 테두리
        band = [any(dark[y][xx] for xx in range(max(0, x - 1), min(w, x + 2))) for y in range(h)]
        for a, b in _runs(band, int(V_RUN * h)):
            for y in range(a, b):
                line[y][x] = True
    ink = sum(1 for y in range(h) for x in range(w) if dark[y][x] and not line[y][x])
    return ink / (w * h)


def _typed(words, box) -> bool:
    """서명 칸 안에서 OCR이 글자(한글 2자 이상)를 읽으면 워드 작성 서명으로 본다. 손글씨 서명은 보통 글자로 읽히지 않는다."""
    import re

    for w in words:
        cx, cy = _cx(w), _cy(w)
        if box[0] <= cx <= box[2] and box[1] <= cy <= box[3] and len(re.findall(r"[가-힣]", w["text"])) >= 2:
            return True
    return False


def _verdict(im, words, box, key, out):
    r = ink_ratio(im, box)
    out["ink"][key] = round(r, 4)
    if _typed(words, box):
        return "typed"
    return r >= INK_MIN


def signatures_from_scan(pdf: bytes, ocr: dict, attendee_names: list[str], payer_name: str | None) -> dict:
    out = {"attendee_signed": {}, "payer_signed": None, "receipt_image": None, "ink": {}}
    doc = pdfium.PdfDocument(pdf)
    for pi, page in enumerate(ocr.get("pages", [])):
        words = page.get("words", [])
        W = page.get("width") or ocr["metadata"]["pages"][pi]["width"]
        im = doc[pi].render(scale=W / doc[pi].get_width()).to_pil()
        for head in [w for w in words if w["text"] == "서명"]:
            line = {w["text"] for w in _same_line(words, head)}
            name_head = next((w for w in _same_line(words, head) if w["text"] == "이름"), None)
            if name_head is None:
                continue
            half = abs(_cx(head) - _cx(name_head)) * 0.42  # 서명 열 반폭
            hb = _box(head)
            below = [w for w in words if _cy(w) > hb[3] + 4 and abs(_box(w)[0] - _box(name_head)[0]) < 30]  # 이름 열 단어
            if "학번" in line:  # 참석자 표
                rows = [w for w in below if w["text"] in attendee_names]
                ys = sorted(_cy(w) for w in rows)
                pitch = statistics.median([b - a for a, b in zip(ys, ys[1:])]) if len(ys) > 1 else (hb[3] - hb[1]) * 3
                for w in rows:
                    box = (_cx(head) - half, _cy(w) - pitch * 0.45, _cx(head) + half, _cy(w) + pitch * 0.45)
                    out["attendee_signed"][w["text"]] = _verdict(im, words, box, w["text"], out)
            elif payer_name:  # 결제자 표
                row = next((w for w in sorted(below, key=_cy) if w["text"] == payer_name), None)
                if row is not None:
                    pitch = (_cy(row) - _cy(head)) * 0.9
                    box = (_cx(head) - half, _cy(row) - pitch * 0.5, _cx(head) + half, _cy(row) + pitch * 0.5)
                    out["payer_signed"] = _verdict(im, words, box, "(결제자)", out)
    return out
