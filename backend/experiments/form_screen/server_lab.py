"""운영 컨테이너에서 별도 DB로 실제 /api/intake/mail 경로를 시험한다.

make: 가상 데이터·공식 빈 양식으로 MIME 묶음 생성. 학생 원본은 포함하지 않는다.
run: 운영 데이터 경로 접근을 피하도록 import 전에 DB·파일 경로를 임시 폴더로 고정.
검수 enqueue만 막아 판정 AI 호출과 운영 대기열 변경 없이 접수 단계까지 검사한다.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import tempfile
import zipfile
from email.message import EmailMessage
from pathlib import Path


def make(output: Path):
    from run import ROOT, corpus

    labels = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(__file__, "server_lab.py")
        for module in ("app/review/readers.py", "app/mail/intake.py"):
            z.write(ROOT / module, Path(module).name)
        for i, (label, expected, files) in enumerate(corpus()):
            msg = EmailMessage()
            msg["From"] = "Synthetic <synthetic@example.invalid>"
            msg["To"] = "lab@example.invalid"
            msg["Subject"] = f"[수집] 양식 접수 실험 {i}"
            msg["Message-ID"] = f"<form-screen-{i}@example.invalid>"
            msg["Date"] = "Sat, 31 Oct 2026 17:00:00 +0900"
            msg.set_content("가상 실험 본문입니다. 학생 개인정보가 아닙니다.")
            for name, data in files:
                msg.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
            z.writestr(f"mails/{i:03}.eml", msg.as_bytes())
            labels.append({"file": f"mails/{i:03}.eml", "case": label, "expected": expected})
        z.writestr("labels.json", json.dumps(labels, ensure_ascii=False))
    print("synthetic MIME cases", len(labels), "bundle", output)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(folder: Path, variant: str):
    lab = Path(tempfile.mkdtemp(prefix=f"form-screen-{variant}-"))
    os.environ["DATABASE_URL"] = f"sqlite:///{lab / 'app.db'}"
    os.environ["DATA_DIR"] = str(lab / "data")
    os.environ["GMAIL_POLL_MINUTES"] = "0"
    from app.config import get_settings
    from app.db import init_db, session
    from app import worker
    from app.api import intake as endpoint
    from app.main import create_app
    from app.review import readers
    from fastapi.testclient import TestClient
    from sqlalchemy import select, func
    from app.models import Submission, File

    get_settings().intake_since = None
    worker.enqueue = lambda submission_id: None
    init_db()
    if variant == "candidate":
        candidate = load("app.review.lab_readers", folder / "readers.py")
        readers.screen_result, readers.screen, readers.is_minutes = candidate.screen_result, candidate.screen, candidate.is_minutes
        endpoint.intake_raw = load("app.mail.lab_intake", folder / "intake.py").intake_raw
    client = TestClient(create_app())  # lifespan을 시작하지 않아 poller·재검수 작업 없음
    rows, counts = [], dict(tp=0, fp=0, tn=0, fn=0)
    labels = json.loads((folder / "labels.json").read_text())
    for item in labels:
        response = client.post("/api/intake/mail", content=(folder / item["file"]).read_bytes(),
                               headers={"X-Intake-Secret": get_settings().intake_secret, "Content-Type": "message/rfc822"})
        if response.status_code != 201:
            raise RuntimeError(f"intake HTTP {response.status_code}")
        result = response.json()
        accepted = bool(result.get("id"))
        expected = item["expected"]
        counts["tp" if expected and accepted else "fn" if expected else "fp" if accepted else "tn"] += 1
        with session() as db:
            sub = db.get(Submission, result["id"]) if accepted else None
            fields_ok = bool(sub and sub.subject.startswith("양식 접수 실험") and sub.body_text.strip()
                             and sub.files and (get_settings().data_dir / "raw" / f"{sub.id}.eml").exists())
        rows.append({"case": item["case"], "expected": expected, "accepted": accepted,
                     "title_body_attachment_raw_saved": fields_ok if accepted else None})
    with session() as db:
        db_count = db.scalar(select(func.count()).select_from(Submission))
        file_count = db.scalar(select(func.count()).select_from(File))
    report = {"variant": variant, "endpoint": "/api/intake/mail", "transport": "server TestClient HTTP/MIME",
              "ai_called": False, "lab_dir": str(lab), "total": len(rows), **counts, "db_submissions": db_count,
              "db_files": file_count, "pending_files": len(list((get_settings().data_dir / "intake_pending").glob("*"))),
              "accepted_fields_ok": all(r["title_body_attachment_raw_saved"] for r in rows if r["accepted"]), "rows": rows}
    (folder / f"server_{variant}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("mode", choices=["make", "run"])
    p.add_argument("path", type=Path)
    p.add_argument("--variant", choices=["baseline", "candidate"], default="candidate")
    args = p.parse_args()
    make(args.path) if args.mode == "make" else run(args.path, args.variant)
