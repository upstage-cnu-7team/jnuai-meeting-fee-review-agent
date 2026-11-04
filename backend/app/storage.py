"""원본 파일과 쪽 이미지 저장. 원본은 data/files/<sha256>, 쪽 이미지는 data/pages/<file_id>/<n>.png."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import get_settings


def save_original(data: bytes) -> str:
    sha = hashlib.sha256(data).hexdigest()
    d = get_settings().files_dir
    d.mkdir(parents=True, exist_ok=True)
    p = d / sha
    if not p.exists():
        p.write_bytes(data)
    return sha


def original_path(sha: str) -> Path:
    return get_settings().files_dir / sha


def read_original(sha: str) -> bytes:
    return original_path(sha).read_bytes()


def page_path(file_id: str, n: int) -> Path:
    return get_settings().pages_dir / file_id / f"{n}.png"


def save_pages(file_id: str, pngs: list[bytes]):
    d = get_settings().pages_dir / file_id
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.png"):
        old.unlink()
    for i, png in enumerate(pngs, 1):
        (d / f"{i}.png").write_bytes(png)
