"""'양식 검토 대기'로 남긴 메일(양식 아님·팀명 없음)을 보고 지운다. 서버 컨테이너 안에서 실행한다.

    python -m tools.held_mail list               # 접수 번호·받은 시각·이유·첨부 (본문은 출력하지 않음)
    python -m tools.held_mail delete <id> ...    # 종희가 확인한 것만 지운다: DB 기록·첨부 원본·미리보기·.eml

자동으로 지우지 않는다. 종희가 목록을 보고 관련 없는 메일이라고 확인한 것만 지운다 (2026-11-02).
"""
from __future__ import annotations

import shutil
import sys

from sqlalchemy import select

from app.config import get_settings
from app.db import session
from app.mail.intake import HELD_PREFIX
from app.models import File, Submission


def held(db) -> list[Submission]:
    return [s for s in db.scalars(select(Submission).order_by(Submission.received_at)) if (s.processing_error or "").startswith(HELD_PREFIX)]


def list_held():
    with session() as db:
        rows = held(db)
        for s in rows:
            files = ", ".join(f"{f.name.rsplit('.', 1)[-1]} {f.size // 1024}KB" for f in s.files) or "첨부 없음"
            print(f"{s.id}  {s.received_at:%m/%d %H:%M}  {s.processing_error[len(HELD_PREFIX):][:80]}  [{files}]")
        print(f"양식 검토 대기 {len(rows)}건")


def delete(ids: list[str]):
    st = get_settings()
    with session() as db:
        for i in ids:
            sub = db.get(Submission, i)
            if sub is None or not (sub.processing_error or "").startswith(HELD_PREFIX):
                print(i, "양식 검토 대기가 아니어서 건너뜀")
                continue
            files = [(f.id, f.sha256) for f in sub.files]
            db.delete(sub)
            db.commit()
            for fid, sha in files:
                shutil.rmtree(st.pages_dir / fid, ignore_errors=True)
                if not db.scalar(select(File).where(File.sha256 == sha)):
                    (st.files_dir / sha).unlink(missing_ok=True)
            (st.data_dir / "raw" / f"{i}.eml").unlink(missing_ok=True)
            print(i, f"삭제 (첨부 {len(files)}개)")


if __name__ == "__main__":
    if sys.argv[1:2] == ["list"]:
        list_held()
    elif sys.argv[1:2] == ["delete"] and sys.argv[2:]:
        delete(sys.argv[2:])
    else:
        print(__doc__)
