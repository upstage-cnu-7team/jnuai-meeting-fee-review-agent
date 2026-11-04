"""noreply@jnuai-meetingfee.com → 담당자 주소로 '[발송요청]' 메일 보내기 실험 (Resend).

    cd backend
    uv run python experiments/mail_send/send_request.py <받는 주소> "<제목>" "<본문>"

- 키는 backend/.env 의 RESEND_API_KEY 에서 읽는다. 화면에 찍지 않는다.
- 흐름 ②는 제목 '[발송요청] <토큰> <MSGID>' 의 마지막 단어를 원래 메일 ID로 쓴다.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[2] / ".env"
SENDER = "회의비 검토 서비스 <noreply@jnuai-meetingfee.com>"


def api_key() -> str:
    for line in ENV.read_text().splitlines() if ENV.exists() else []:
        if line.startswith("RESEND_API_KEY="):
            return line.split("=", 1)[1].strip()
    return os.environ.get("RESEND_API_KEY") or sys.exit("RESEND_API_KEY가 backend/.env에 없습니다.")


def main():
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    to, subject, body = sys.argv[1:]
    r = httpx.post("https://api.resend.com/emails", timeout=30,
                   headers={"Authorization": f"Bearer {api_key()}"},
                   json={"from": SENDER, "to": [to], "subject": subject, "text": body})
    print(r.status_code, r.text[:300])


if __name__ == "__main__":
    main()
