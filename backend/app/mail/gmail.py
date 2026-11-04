"""Gmail에서 수집 메일 가져오기 (Email Worker 웹훅이 붙기 전 임시 경로).

submit@jnuai-meetingfee.com → Cloudflare Email Routing → Gmail로 전달된 '[수집]' 메일을 IMAP으로 읽어 접수한다.
- 로그인: Gmail 주소 + 앱 비밀번호(.env GMAIL_ADDRESS·GMAIL_APP_PASSWORD, 사용자가 직접 넣음). 메일함 설정은 바꾸지 않는다.
- 가져오는 메일: 제목에 '[수집'이 있고 INTAKE_SINCE 날짜 이후. 읽음 표시를 바꾸지 않도록 BODY.PEEK로 읽는다.
- 같은 메일은 원본 Message-ID로 중복을 막으므로 여러 번 돌려도 된다.
"""
from __future__ import annotations

import imaplib
import logging
import threading
from datetime import timedelta

from ..config import get_settings
from ..db import session
from .intake import IntakeResult, intake_raw

log = logging.getLogger("gmail")


def fetch(limit: int = 200) -> list[tuple[str, IntakeResult]]:
    s = get_settings()
    if not (s.gmail_address and s.gmail_app_password):
        raise RuntimeError("GMAIL_ADDRESS·GMAIL_APP_PASSWORD가 설정되지 않았습니다")
    since = (s.intake_since - timedelta(days=1)) if s.intake_since else None
    out = []
    with imaplib.IMAP4_SSL("imap.gmail.com") as im:
        im.login(s.gmail_address, s.gmail_app_password)
        im.select("INBOX", readonly=True)  # 읽기 전용: 읽음 표시·폴더를 바꾸지 않는다
        raw_query = 'subject:"[수집"' + (f" after:{since:%Y/%m/%d}" if since else "")
        typ, data = im.search(None, "X-GM-RAW", f'"{raw_query.replace(chr(34), chr(92) + chr(34))}"')
        ids = data[0].split()[-limit:] if typ == "OK" and data and data[0] else []
        for i in ids:
            typ, msg = im.fetch(i, "(BODY.PEEK[])")
            if typ != "OK" or not msg or not isinstance(msg[0], tuple):
                continue
            with session() as db:
                r = intake_raw(db, msg[0][1])
            out.append((i.decode(), r))
    return out


def start_poller():
    """GMAIL_POLL_MINUTES > 0이면 서버 안에서 주기적으로 가져온다."""
    s = get_settings()
    if not (s.gmail_address and s.gmail_app_password and s.gmail_poll_minutes > 0):
        return
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                got = fetch()
                new = sum(1 for _, r in got if r.id and not r.duplicate)
                if new:
                    log.info("gmail: 새 제출 %d건", new)
            except Exception as e:  # 연결 오류 등. 메일 내용은 남기지 않는다
                log.warning("gmail 가져오기 실패: %s", type(e).__name__)
            stop.wait(s.gmail_poll_minutes * 60)

    threading.Thread(target=loop, name="gmail-poller", daemon=True).start()
    return stop
