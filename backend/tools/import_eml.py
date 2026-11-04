"""Gmail 등에서 내려받은 메일 원본(.eml)을 한꺼번에 접수한다. 웹훅(Email Worker)이 붙기 전 쌓인 메일용.

웹훅과 같은 규칙을 쓴다: INTAKE_SINCE 이전 메일·회의비 증빙 양식이 아닌 첨부만 있는 메일은 건너뛰고, Message-ID로 중복을 막는다.
접수한 건은 바로 검수한다(Upstage 호출, 키 필요).

Gmail에서 .eml 받기: 메일 열기 → 오른쪽 위 ⋮ → '메일 다운로드'

    cd backend && uv run python tools/import_eml.py <eml 폴더 또는 파일...>
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402

from app.mail.intake import parse_mail  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.models import Submission  # noqa: E402
from app.review import readers  # noqa: E402
from app.seed import seed_basics  # noqa: E402
from app.worker import create_submission, run_review  # noqa: E402


def main(paths: list[str]):
    init_db()
    seed_basics()
    since = get_settings().intake_since
    files = sorted(p for a in paths for p in (Path(a).glob("*.eml") if Path(a).is_dir() else [Path(a)]))
    done = skipped = 0
    for p in files:
        m = parse_mail(p.read_bytes())
        if since and m["received_at"] and m["received_at"] < since:
            why = f"접수 시작({since:%m/%d %H:%M}) 이전"
        else:
            why = readers.screen(m["files"])
        with session() as db:
            if not why and m["message_id"] and db.scalar(select(Submission).where(Submission.mail_message_id == m["message_id"])):
                why = "이미 접수됨"
            if why:  # 메일 내용(이름·제목)은 찍지 않는다
                print(f"건너뜀  {p.name}: {why}")
                skipped += 1
                continue
            sub = create_submission(db, **m)
            sid = sub.id
        run_review(sid)
        with session() as db:
            s = db.get(Submission, sid)
            print(f"접수    {p.name} → {sid} {s.processing_status} {s.program or '프로그램 미확정'} {s.verdict or ''}")
        done += 1
    print(f"접수 {done}건, 건너뜀 {skipped}건")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    main(sys.argv[1:])
