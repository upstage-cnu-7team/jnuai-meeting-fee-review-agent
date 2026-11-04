"""Gmail로 전달된 '[수집]' 메일을 가져와 접수·검수한다 (Email Worker 웹훅 전 임시 경로).

.env: GMAIL_ADDRESS, GMAIL_APP_PASSWORD(앱 비밀번호, 직접 넣음), INTAKE_SINCE, MANAGER_MAILBOXES
    cd backend && uv run python tools/fetch_gmail.py
서버를 켜 둔 채 자동으로 가져오려면 .env에 GMAIL_POLL_MINUTES=5 를 둔다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.db import init_db  # noqa: E402
from app.mail.gmail import fetch  # noqa: E402
from app.seed import seed_basics  # noqa: E402

if __name__ == "__main__":
    get_settings().run_review_inline = True  # 이 스크립트 안에서 검수까지 끝낸다
    init_db()
    seed_basics()
    got = fetch()
    new = [r.id for _, r in got if r.id and not r.duplicate]
    dup = sum(1 for _, r in got if r.duplicate)
    skipped = [r.skipped for _, r in got if r.skipped]
    print(f"가져온 메일 {len(got)}통 → 새 제출 {len(new)}건, 이미 있음 {dup}건, 건너뜀 {len(skipped)}건")
    for why in sorted(set(skipped)):
        print(f"  건너뜀 {skipped.count(why)}건: {why}")
