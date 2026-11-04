"""메일 본문의 대용량 첨부 링크(네이버 메일 '대용량 첨부' 등)에서 파일을 받아 온다.

네이버 메일은 10MB를 넘는 파일을 MIME 첨부가 아니라 본문 링크로 보낸다(2026-10-30 전자파 동아리 36MB HWP).
링크는 로그인 없이 바로 받아지고(Content-Disposition에 파일 이름), 30일·100회 제한이 있다.
받기 실패(만료·접근 실패)는 학생 미제출이 아니므로 담당자 메모로만 남긴다.
"""
from __future__ import annotations

import logging
import re
from email.utils import collapse_rfc2231_value, decode_rfc2231
from urllib.parse import unquote

import httpx

log = logging.getLogger("intake")

# 대용량 첨부를 바로 내려받는 주소만 받는다(MYBOX 저장·수신 확인 같은 다른 링크는 무시)
LINK_PATTERNS = [re.compile(r"https://bigfile\.mail\.naver\.com/download\?fid=[A-Za-z0-9+/=%_-]+")]
MAX_BYTES = 100 * 1024 * 1024


def find_links(text: str) -> list[str]:
    out = []
    for pat in LINK_PATTERNS:
        for url in pat.findall(text or ""):
            if url not in out:
                out.append(url)
    return out


def _filename(disposition: str, fallback: str) -> str:
    m = re.search(r"filename\*=([^;]+)", disposition or "")
    if m:
        v = m[1].strip().strip('"')
        if "''" in v:
            return unquote(v.split("''", 1)[1])
        return collapse_rfc2231_value(decode_rfc2231(v))
    m = re.search(r'filename="?([^";]+)"?', disposition or "")
    return m[1] if m else fallback


def fetch(url: str, client: httpx.Client | None = None) -> tuple[str, bytes]:
    """링크 하나를 받는다 → (파일 이름, 바이트). 실패하면 예외."""
    c = client or httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    with c.stream("GET", url) as r:
        r.raise_for_status()
        if int(r.headers.get("content-length") or 0) > MAX_BYTES:
            raise ValueError("파일이 너무 큼")
        buf = bytearray()
        for chunk in r.iter_bytes():
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("파일이 너무 큼")
        if r.headers.get("content-type", "").startswith("text/html"):
            raise ValueError("파일 대신 안내 화면이 왔음(만료 가능)")
        return _filename(r.headers.get("content-disposition", ""), "대용량첨부"), bytes(buf)


def fetch_all(text: str, have_names: set[str], client: httpx.Client | None = None) -> tuple[list[tuple[str, bytes]], list[str]]:
    """본문의 대용량 링크를 모두 받는다 → (받은 파일들, 담당자 메모). 이미 받은 이름은 건너뛴다."""
    files, notes = [], []
    for url in find_links(text):
        try:
            name, data = fetch(url, client)
        except Exception as e:  # 링크 주소·내용은 로그에 남기지 않는다
            log.warning("bigfile link failed: %s", type(e).__name__)
            notes.append("메일 본문의 대용량 첨부 링크에서 파일을 받지 못했습니다(링크 만료·접근 실패 가능). "
                         "학생 미제출이 아니니 메일 원문에서 파일을 직접 확인해 주세요.")
            continue
        if name not in have_names:
            files.append((name, data))
            have_names.add(name)
    return files, notes
