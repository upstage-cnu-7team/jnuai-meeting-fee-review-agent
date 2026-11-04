"""회귀 시험용 가상 케이스 18건 × 4형식(hwp·pdf·docx·scan) 생성.

생성 파일 바이트가 매번 같아야 Upstage 응답 캐시(파일 해시 키)가 맞는다.
- PDF: reportlab invariant 모드 (생성 시각·문서 ID 고정)
- DOCX: zip 안 파일 시각을 고정해 다시 묶는다 (내용은 원래 같다)
- scan: 고정 PDF를 scanify(seed=0)로 이미지 PDF로
"""
from __future__ import annotations

import io
import re
import sys
import zipfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = BACKEND / "forms" / "aicollege" / "별첨1-1_회의비_지출증빙_양식.hwp"
FIXTURES = BACKEND / "tests" / "fixtures" / "upstage"
FORMATS = ["hwp", "pdf", "docx", "scan"]


def _stable_docx(data: bytes) -> bytes:
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 1, 1, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(zi, src.read(info.filename))
    return out.getvalue()


def _stable_pdf_dates(data: bytes) -> bytes:
    """PIL이 넣는 생성·수정 시각을 고정한다 (길이는 그대로)."""
    return re.sub(rb"/(CreationDate|ModDate) ?\(D:[^)]*\)", lambda m: re.sub(rb"\d", b"0", m[0]), data)


def build(out: Path) -> list[tuple[dict, str, Path]]:
    """케이스 파일을 out/에 만들고 (case, format, path) 목록을 돌려준다."""
    sys.path.insert(0, str(BACKEND))
    import reportlab.rl_config as rl

    rl.invariant = 1
    from tools import aicollege_samples as gen
    from tools.scanify import scanify

    out.mkdir(parents=True, exist_ok=True)
    tpl = TEMPLATE.read_bytes()
    jobs = []
    for c in gen.CASES:
        pdf = gen.write_pdf(c)
        files = {"hwp": gen.write_hwp(c, tpl), "pdf": pdf, "docx": _stable_docx(gen.write_docx(c)), "scan": _stable_pdf_dates(scanify(pdf, 0))}
        for fmt in FORMATS:
            p = out / f"{c['name']}.{fmt}" if fmt != "scan" else out / f"{c['name']}.scan.pdf"
            p.write_bytes(files[fmt])
            jobs.append((c, fmt, p))
    return jobs
