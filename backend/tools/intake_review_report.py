"""검토 모드로 보존한 메일을 서버의 비공개 HTML 검토 자료로 내보낸다.

메일 본문·첨부는 지정 출력 폴더에만 쓰고 stdout에는 집계만 출력한다.
    python -m tools.intake_review_report /tmp/meetingfee-mail-review
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from app.config import get_settings
from app.mail.intake import parse_mail
from app.review import readers, team_match
from app.review.form_check import check_document


def build(output: Path, new_only: bool = False):
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = get_settings().data_dir / "intake_review"
    ai_path = source / "ai_results.json"
    ai_results = json.loads(ai_path.read_text()) if ai_path.exists() else {}
    initial_path = source / "ai_results_initial.json"
    initial_results = json.loads(initial_path.read_text()) if initial_path.exists() else {}
    mails = []
    for p in source.glob("*.eml"):
        outcome = p.with_suffix(".json")
        if not outcome.exists():
            continue
        result = json.loads(outcome.read_text())
        if new_only and result.get("duplicate"):
            continue
        m = parse_mail(p.read_bytes())
        mails.append((m, p, result))
    mails.sort(key=lambda x: (str(x[0]["received_at"]), x[1].name))
    records, cards = [], []
    for i, (m, p, result) in enumerate(mails, 1):
        folder = output / f"mail_{i:02}"
        folder.mkdir(exist_ok=True, mode=0o700)
        (folder / "original.eml").write_bytes(p.read_bytes())
        decision, why = readers.screen_result(m["files"])
        files, links = [], []
        for k, (name, data) in enumerate(m["files"], 1):
            suffix = Path(name).suffix
            suffix = suffix if len(suffix) < 10 and suffix[1:].isalnum() else ".bin"
            # 바로가기·일정은 실행하지 않고 텍스트로 확인할 수 있게 내보낸다.
            target = folder / f"attachment_{k:02}{'.txt' if suffix.lower() in ('.url', '.ics') else suffix}"
            target.write_bytes(data)
            fmt, doc = readers.classify(data, name)
            form = check_document(doc)
            fields = readers.form_fields(doc)
            item = {"name": name, "file": str(target.relative_to(output)), "format": fmt,
                    "readable": doc is not None, "form_status": form.status, "form_ratio": form.ratio,
                    "missing_labels": form.missing, "form_program": team_match.program_from_form_title(readers.full_text(doc)),
                    "form_team": fields.get("team_name"), "local_form": readers.is_minutes(doc, fmt)}
            files.append(item)
            preview = ""
            if fmt == "pdf":
                preview = f'<details><summary>PDF 미리보기</summary><embed src="{item["file"]}" type="application/pdf" width="100%" height="700"></details>'
            elif doc is not None and fmt in ("hwp", "hwpx", "docx"):
                from app.review.pages import render_pages

                try:
                    images = render_pages(data, fmt, doc)
                    paths = []
                    for pi, png in enumerate(images[:2], 1):
                        image_path = folder / f"attachment_{k:02}_page_{pi}.png"
                        image_path.write_bytes(png)
                        paths.append(f'<img style="max-width:100%" src="{image_path.relative_to(output)}">')
                    preview = '<details><summary>첫 2쪽 미리보기(리더가 재구성, 원본 링크도 확인)</summary>' + "".join(paths) + '</details>'
                except Exception:
                    preview = "<p>미리보기 생성 실패 — 원본 링크로 확인해 주세요.</p>"
            links.append(f'<li><a href="{item["file"]}">{html.escape(name)}</a> — {fmt}, '
                         f'양식 칸 {form.ratio:.0%}, 로컬 판별 {item["local_form"]}, '
                         f'양식 프로그램 {html.escape(team_match.NAMES.get(item["form_program"], "제목 표기 없음"))}{preview}</li>')
        record = {"n": i, "received_at": str(m["received_at"]), "subject": m["subject"], "body": m["body_text"],
                  "result": result, "screen_decision": decision, "screen_reason": why,
                  "mail_programs": team_match.program_from_mail(m["subject"] + "\n" + m["body_text"]), "attachments": files}
        record["ai_form"] = ai_results.get(p.stem)
        record["ai_initial"] = initial_results.get(p.stem)
        if result.get("id"):
            from app.db import session
            from app.models import Submission

            with session() as db:
                sub = db.get(Submission, result["id"])
                if sub:
                    record["service"] = {"program": sub.program, "processing_status": sub.processing_status,
                        "processing_error": sub.processing_error, "team_reason": sub.team_match_reason,
                        "model_info": sub.model_info, "verdict": sub.verdict}
        records.append(record)
        status = "기존 접수 중복" if result.get("duplicate") else "비대상 후보 · 원본 검토 보존" if decision == "not_form" else "회의비 양식 후보"
        service = html.escape(json.dumps(record.get("service", {}), ensure_ascii=False, indent=2))
        ai = record["ai_form"] or {}
        program = team_match.NAMES.get(record.get("service", {}).get("program"), "미확정")
        first = record["ai_initial"] or {}
        first_note = (f'<p style="color:#a23">첫 AI 판별: {html.escape(first.get("decision", ""))} · '
                      f'{html.escape(first.get("evidence", ""))}</p>' if first and first.get("decision") != ai.get("decision") else "")
        detail = (f'<a target="_blank" href="https://meeting-fee-review-agent-front.vercel.app/submissions/{result["id"]}">서비스 상세 열기</a>'
                  if result.get("id") else "")
        cards.append(f'<article id="mail{i}"><h2>{i:02}. {html.escape(m["subject"])}</h2>'
                     f'<p>{html.escape(str(m["received_at"]))} · {status} · {decision}</p>'
                     f'<p>{html.escape(why or "")}<br>메일 프로그램 표기: {html.escape(str(record["mail_programs"]))}</p>'
                     f'<p><b>AI 양식 판별: {html.escape(ai.get("decision", "대기"))}</b> · '
                     f'{html.escape(ai.get("evidence", ""))}</p>'
                     f'<p>서비스 프로그램: <b>{program}</b> · AI 프로그램: '
                     f'{html.escape(team_match.NAMES.get(ai.get("program"), "미확정"))}</p>'
                     f'{first_note}'
                     f'<ul>{"".join(links) or "<li>첨부 없음</li>"}</ul>'
                     f'<details><summary>메일 본문</summary><pre>{html.escape(m["body_text"])}</pre></details>'
                     f'<details><summary>서비스 처리 결과</summary><pre>{service}</pre></details>'
                     f'<p><a href="mail_{i:02}/original.eml">메일 원본</a> · {detail}</p><p>'
                     '내 판단: <label><input type="radio" name="human' + str(i) + '"> 회의비 양식</label> '
                     '<label><input type="radio" name="human' + str(i) + '"> 비대상</label> '
                     '<label><input type="radio" name="human' + str(i) + '"> 확인 필요</label></p></article>')
    (output / "review.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "index.html").write_text('<!doctype html><meta charset="utf-8"><title>재전송 메일 검토</title>'
        '<style>body{font:16px sans-serif;max-width:1000px;margin:40px auto;padding:0 20px}article{border:1px solid #ccc;'
        'padding:24px;margin:20px 0}pre{white-space:pre-wrap}label{margin-right:15px}a{color:#1259ac}</style>'
        '<h1>재전송 메일 하나씩 검토</h1><p>개인정보 포함 · 비공개 로컬 검토 자료. 코드 결과와 별도 Solar 양식 분류를 나란히 표시합니다. '
        '선택은 이 브라우저에만 저장됩니다. 번호로 판단을 알려 주세요.</p>' + "".join(cards) +
        '<script>document.querySelectorAll("input[type=radio]").forEach((e)=>{'
        'e.value=e.parentElement.textContent.trim();try{e.checked=localStorage.getItem("meetingfee-review-"+e.name)===e.value}catch(_){}'
        'e.onchange=()=>{try{localStorage.setItem("meetingfee-review-"+e.name,e.value)}catch(_){}}})</script>', encoding="utf-8")
    print(json.dumps({"mails": len(records), "attachments": sum(len(r["attachments"]) for r in records),
                      "duplicates": sum(bool(r["result"].get("duplicate")) for r in records),
                      "skipped": sum(bool(r["result"].get("skipped")) for r in records)}))


if __name__ == "__main__":
    build(Path(sys.argv[1]), "--new-only" in sys.argv[2:])
