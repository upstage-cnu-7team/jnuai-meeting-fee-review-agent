"""시연용 제출 건을 로컬 DB에 넣는다. 가상 케이스 + 회귀 fixture 캐시를 써서 Upstage를 부르지 않는다.

    cd backend && uv run python tools/seed_demo.py [--reset]

--reset: data/app.db와 data/files·pages를 지우고 처음부터 만든다(계정은 .env 비밀번호로 다시 생김).
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from aicollege_cases import FIXTURES  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import init_db, session  # noqa: E402
from app.models import Submission  # noqa: E402
from app.review import upstage  # noqa: E402
from app.seed import seed_basics  # noqa: E402
from app.worker import create_submission, run_review  # noqa: E402

# (케이스, 형식, 팀(회의록 팀명 칸과 메일 제목에 같이 넣음), 보낸 사람)
# 가상 회의록은 모두 사업단 '동아리' 양식(별첨 1-1)이라 동아리 메일함으로만 넣는다.
DEMO = [
    ("A13_서명누락", "hwp", "AfterandAfter", "김하늘"),
    ("A04_20시이후", "docx", "Creeper", "이도윤"),
    ("A01_정상", "pdf", "DeepDive", "박서준"),
    ("A11_카페장소", "hwp", "TWBD", "최지우"),
    ("A08_다과비시각", "pdf", "VCCC", "정민재"),
    ("A17_결제자서명누락", "scan", "너만보인단말이야", "한유나"),
    ("A15_제출기한초과", "docx", "오야지치", "윤서연"),
    ("A02_날짜불일치", "pdf", "클래시파이", "강태오"),
    ("A10_북구밖", "hwp", "코드메이트", "송다인"),  # 팀 목록에 없는 팀명 → 팀 미확정
]


def make_file(case: dict, fmt: str, team: str) -> tuple[str, bytes]:
    """케이스의 팀명 칸을 바꿔 회의록 파일을 만든다 (aicollege_cases와 같은 바이트 고정 방식)."""
    import copy

    import reportlab.rl_config as rl

    import aicollege_cases as ac
    from tools import aicollege_samples as gen
    from tools.scanify import scanify

    rl.invariant = 1
    c = copy.deepcopy(case)
    c["team"] = team
    if fmt == "hwp":
        return f"{team}_회의록.hwp", gen.write_hwp(c, ac.TEMPLATE.read_bytes())
    if fmt == "docx":
        return f"{team}_회의록.docx", ac._stable_docx(gen.write_docx(c))
    pdf = gen.write_pdf(c)
    if fmt == "scan":
        return f"{team}_회의록_스캔.pdf", ac._stable_pdf_dates(scanify(pdf, 0))
    return f"{team}_회의록.pdf", pdf


def main(reset: bool):
    s = get_settings()
    if reset:
        db_path = Path(s.database_url.removeprefix("sqlite:///"))
        for p in (db_path, s.files_dir, s.pages_dir):
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
    init_db()
    seed_basics()
    cache = upstage.Cache(FIXTURES)  # 회귀 fixture를 먼저 보고, 없으면 Upstage를 불러 DB에 캐시
    with tempfile.TemporaryDirectory():
        cases = {c["name"]: c for c in __import__("tools.aicollege_samples", fromlist=["CASES"]).CASES}
        for name, fmt, team, sender in DEMO:
            case = cases[name]
            fname, data = make_file(case, fmt, team)
            with session() as db:
                sub = create_submission(db, files=[(fname, data)], mailbox="club_manager", sender_name=sender,
                                        sender_email=f"{team.lower()[:6] or 'team'}{len(sender)}@jnu.ac.kr" if team.isascii() else f"student{abs(hash(team)) % 1000}@jnu.ac.kr",
                                        subject=f"[동아리] {team} 10월 회의비 증빙 제출합니다",
                                        body_text=f"안녕하세요 담당자님, {team} 팀 회의비 증빙 보내드립니다.\n{sender} 드림",
                                        received_at=datetime.fromisoformat(case["submitted_at"]))
                sid = sub.id
            run_review(sid, cache)
            with session() as db:
                x = db.get(Submission, sid)
                print(f"{sid} {name}.{fmt} 팀명 '{team}' → {x.processing_status} {x.program} {x.team.name if x.team else '팀 미확정'} {x.verdict}"
                      + (f" [{x.processing_error}]" if x.processing_error else ""))
        # 첨부 없는 메일 1건 (프로그램 미확정 → 미첨부 보완 요청)
        with session() as db:
            sub = create_submission(db, files=[], mailbox="club_manager", sender_name="조은별", sender_email="eunbyeol@jnu.ac.kr",
                                    subject="회의비 제출합니다", body_text="첨부를 깜빡했습니다.", received_at=datetime(2026, 10, 30, 9, 12))
            sid = sub.id
        run_review(sid, cache)
        print(f"{sid} 첨부 없음 → 프로그램 미확정")
    print("완료: uv run uvicorn app.main:app --reload")


if __name__ == "__main__":
    main("--reset" in sys.argv)
