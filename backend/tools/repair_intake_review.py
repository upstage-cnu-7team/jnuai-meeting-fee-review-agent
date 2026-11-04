"""검토 모드에 보존된 신규 수신분만 재파싱하여 첨부 인코딩 손상을 복구한다.

기본은 집계만 출력. --apply는 해당 수신분의 기존 File 레코드를 복구하고 정상 양식을 재검수한다.
기존 중복 메일·다른 제출은 변경하지 않는다. 원본·옛 blob은 삭제하지 않는다.
"""
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

from app import worker
from app.config import get_settings
from app.db import session
from app.mail.intake import parse_mail
from app.models import Submission
from app.review import readers
from app.storage import save_original


def main(apply: bool):
    root = get_settings().data_dir / "intake_review"
    counts, queued = Counter(), []
    if apply:
        # 수정 전 DB를 같은 비공개 서버 폴더 안에 보관한다.
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            with sqlite3.connect(url.removeprefix("sqlite:///")) as source, sqlite3.connect(root / "before_attachment_repair.db") as backup:
                source.backup(backup)
    for p in root.glob("*.eml"):
        outcome = p.with_suffix(".json")
        if not outcome.exists():
            continue
        result = json.loads(outcome.read_text())
        if result.get("duplicate") or not result.get("id"):
            continue
        mail = parse_mail(p.read_bytes())
        decision, reason = readers.screen_result(mail["files"])
        counts[decision] += 1
        if not apply:
            continue
        with session() as db:
            sub = db.get(Submission, result["id"])
            if not sub or len(sub.files) != len(mail["files"]):
                raise ValueError("복구 대상 첨부 개수 불일치")
            for fi, (name, data) in zip(sorted(sub.files, key=lambda f: f.order), mail["files"]):
                fi.sha256, fi.size, fi.name = save_original(data), len(data), name
                fi.pages, fi.page_count = [], 0
                fi.format = readers.classify(data, name)[0]
            sub.extracted, sub.verdict = None, None
            if decision == "not_form":
                sub.processing_status = "failed"
                sub.processing_error = "양식 검토 대기: " + (reason or "회의비 증빙 양식으로 확인되지 않음")
            else:
                sub.processing_status, sub.processing_error = "queued", None
                queued.append(sub.id)
            db.commit()
    print(json.dumps({"apply": apply, "decisions": counts, "to_review": len(queued)}), flush=True)
    for sid in queued:
        worker.run_review(sid)
        with session() as db:
            sub = db.get(Submission, sid)
            print(json.dumps({"id": sid, "status": sub.processing_status, "program": sub.program, "verdict": sub.verdict}), flush=True)


if __name__ == "__main__":
    main("--apply" in sys.argv)
