"""API 흐름 시험: 업로드 → LangGraph 검수 → 목록·상세·수정·회신·팀·기준·웹훅.

Upstage는 가짜로 바꾼다(추출값은 케이스 내용 그대로). 문서 리더·칸 안 그림·쪽 이미지·판정·초안은 실제 코드가 돈다.
"""
from __future__ import annotations

import copy
from email.message import EmailMessage
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

import os

from aicollege_cases import FIXTURES, build

PW = "test-pw-1234"


def fake_ie(case: dict) -> dict:
    r = case["receipt"]
    return {
        "team_name": "테라바이트", "meeting_title": case["title"] if "title" in case else "MVP 범위 확정", "meeting_date": str(case["date"]),
        "start_time": case["start"], "end_time": case["end"], "place": case["place"], "content": "\n".join(case["content"]),
        "attendees": [{"affiliation": a, "student_id": s, "name": n, "has_signature": False} for a, s, n, _ in case["attendees"]],
        "writer_name": case["writer"], "used_amount": int(case["amount"].replace(",", "")),
        "payer_affiliation": case["payer"][0], "payer_name": case["payer"][1], "payer_has_signature": False,
        "receipt_attached": False, "receipt_type": r.get("title"), "merchant_name": r.get("merchant"), "merchant_address": r.get("address"),
        "card_type": r.get("card_type"), "card_number": r.get("card_no"), "approval_number": r.get("approval"),
        "transaction_datetime": r.get("datetime", "")[:16], "receipt_items": [{"name": n, "quantity": q, "amount": a} for n, q, a in r["items"]],
        "receipt_total": r["total"],
    }


SJ = {k: {"decision": "ok", "reason": "문제 없음"} for k in ("place", "alcohol", "content")} | {"expense_kind": {"kind": "식비", "reason": "식사 품목"}}


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    # 회의록 팀명 칸을 실제 팀(테라바이트)으로 채운 파일을 쓴다. 서버는 칸 값을 우선하므로 가짜 추출값과 파일이 같아야 한다.
    from tools.seed_demo import make_file

    (tmp / "cases").mkdir()
    cases = {}
    for c, fmt, _ in build(tmp / "_orig"):
        name, data = make_file(c, fmt, "테라바이트")
        path = tmp / "cases" / f"{c['name']}.{'pdf' if fmt == 'scan' else fmt}"
        path.write_bytes(data)
        cases[(c["name"], fmt)] = (c, path)
    mp = pytest.MonkeyPatch()
    for k, v in {"DATABASE_URL": f"sqlite:///{tmp / 'app.db'}", "DATA_DIR": str(tmp / "data"), "SEED_PASSWORD_CLUB": PW,
                 "SEED_PASSWORD_WEMEET": PW, "SEED_PASSWORD_ADMIN": PW, "RUN_REVIEW_INLINE": "true", "INTAKE_SECRET": "hook-secret",
                 "SECRET_KEY": "test-secret-0123456789-0123456789-abc"}.items():
        mp.setenv(k, v)
    from app import config, db

    config.get_settings.cache_clear()
    config.get_settings().intake_since = None  # 개발자 .env의 접수 시작 시각이 시험에 섞이지 않게
    db.reset_engine()
    from app.review import upstage

    by_hash = {}
    for (name, fmt), (case, path) in cases.items():
        by_hash[upstage.ie_key(path.read_bytes())] = fake_ie(case)
    mp.setattr(upstage, "extract", lambda data, cache: copy.deepcopy(by_hash.get(upstage.ie_key(data), {})))  # 영수증 사진 재추출은 빈 값
    mp.setattr(upstage, "solar", lambda ie, cache: SJ)
    # 스캔으로 읽히는 시험 파일의 OCR은 tests/fixtures 캐시로 (키 없이 오프라인). 새로 만들 때만 WRITE_OCR_FIXTURES=1 + 키
    ocr_cache = upstage.Cache(FIXTURES, use_db=False, write_fixtures=bool(os.environ.get("WRITE_OCR_FIXTURES")))
    mp.setattr(upstage, "ocr", lambda data, name, cache, _ocr=upstage.ocr: _ocr(data, name, ocr_cache))
    from app.main import create_app

    with TestClient(create_app()) as client:
        yield client, cases
    mp.undo()
    config.get_settings.cache_clear()
    db.reset_engine()


def login(client, who="club-manager") -> dict:
    r = client.post("/api/auth/login", json={"username": who, "password": PW})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(client, h, path, **form):
    form = {"subject": "[동아리] 테라바이트 10월 회의비 증빙", "received_at": "2026-10-16T10:00:00+09:00", **form}
    r = client.post("/api/dev/intake", headers=h, data=form, files=[("files", (path.name, path.read_bytes()))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_auth(env):
    client, _ = env
    assert client.post("/api/auth/login", json={"username": "club-manager", "password": "x"}).json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert client.get("/api/auth/me").status_code == 401
    h = login(client)
    assert client.get("/api/auth/me", headers=h).json() == {"name": "동아리 담당자", "role": "manager", "programs": ["club", "aim", "hackathon"]}
    r = client.get("/api/programs/wemeet/submissions", headers=h)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN"


def test_review_flow(env):
    client, cases = env
    h = login(client)
    sid = upload(client, h, cases[("A13_서명누락", "hwp")][1])
    d = client.get(f"/api/submissions/{sid}", headers=h).json()
    assert d["processing_status"] == "done", d["processing_error"]
    assert d["program"] == "club" and d["team"]["name"] == "테라바이트" and d["team"]["match"] == "auto"
    assert d["verdict"] == "needs_fix" and d["reply_status"] == "draft"
    by = {c["check_id"]: c for c in d["checks"]}
    assert by["R14"]["result"] == "unmet" and "박다솜" in by["R14"]["message"]
    assert [c["check_id"] for c in d["checks"]][0] == "R14"  # 미충족이 먼저
    assert by["R18"]["result"] == "excluded"
    assert d["extracted"]["attendees"][0]["student_id"] == "2024*****"
    assert "****" in d["extracted"]["receipt"]["card_number"]
    assert "박다솜" in d["reply"]["body"] and d["reply"]["compose_url"].startswith("https://email.jnu.ac.kr/owa/")
    assert d["rule_set"]["id"] == "rs_club_v2"

    # 쪽 이미지·다운로드: 로그인 헤더 없이 서명 URL로
    att = d["attachments"][0]
    assert att["kind"] == "minutes" and att["format"] == "hwp" and att["page_count"] >= 1
    img = client.get(att["pages"][0]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    bad = urlparse(att["pages"][0]["url"]).path + "?exp=1&sig=00"
    assert client.get(bad).status_code == 403
    assert client.get(att["download_url"]).content == cases[("A13_서명누락", "hwp")][1].read_bytes()

    # 목록·요약·팀
    lst = client.get("/api/programs/club/submissions", headers=h).json()
    item = next(i for i in lst["items"] if i["id"] == sid)
    assert item["summary"]["failed_checks"] == ["참석자 전원 서명 (자필·전자, 워드 작성 불가)"] and item["summary"]["total_amount"] == 60000
    assert client.get("/api/programs/club/summary", headers=h).json()["needs_fix"] >= 1
    teams = client.get("/api/programs/club/teams", headers=h).json()
    assert teams[0]["name"] == "테라바이트" and teams[-1]["id"] is None

    # 담당자 수정 → 판정·초안 다시 계산
    r = client.patch(f"/api/submissions/{sid}/checks/R14", headers=h, json={"result": "met", "note": "원본 확인함"}).json()
    assert r["verdict"] == "pass" and r["reply_regenerated"] and r["check"]["overridden"] and r["check"]["ai_result"] == "unmet"
    assert client.patch(f"/api/submissions/{sid}/checks/R18", headers=h, json={"result": "met"}).json()["error"]["code"] == "CHECK_EXCLUDED"
    # 초안을 직접 고치면 덮어쓰지 않는다
    assert client.put(f"/api/submissions/{sid}/reply", headers=h, json={"subject": "RE: 확인", "body": "직접 쓴 본문"}).json()["edited_by_manager"]
    r = client.patch(f"/api/submissions/{sid}/checks/R14", headers=h, json={"result": None}).json()
    assert r["verdict"] == "needs_fix" and not r["reply_regenerated"] and r["reply"]["body"] == "직접 쓴 본문"
    assert "박다솜" in client.post(f"/api/submissions/{sid}/reply/regenerate", headers=h).json()["body"]

    # 회신: 직접 발송은 보류(503), 보냈음 표시 → 잠김
    assert client.post(f"/api/submissions/{sid}/reply/send", headers=h).json()["error"]["code"] == "MAIL_BRIDGE_DOWN"
    assert client.post(f"/api/submissions/{sid}/reply/mark-sent", headers=h).json() == {"review_status": "confirmed", "reply_status": "sent"}
    assert client.put(f"/api/submissions/{sid}/reply", headers=h, json={"subject": "x", "body": "y"}).json()["error"]["code"] == "REPLY_LOCKED"
    d = client.patch(f"/api/submissions/{sid}", headers=h, json={"review_status": "pending"}).json()
    assert d["review_status"] == "pending" and d["reply_status"] == "sent"


def test_previous_submission_and_team_patch(env):
    client, cases = env
    h = login(client)
    first = upload(client, h, cases[("A01_정상", "pdf")][1])
    second = upload(client, h, cases[("A06_1인당초과", "docx")][1], received_at="2026-10-17T09:00:00+09:00")
    d = client.get(f"/api/submissions/{second}", headers=h).json()
    assert d["verdict"] == "reject" and first in [p["id"] for p in d["previous_submissions"]]
    first_d = client.get(f"/api/submissions/{first}", headers=h).json()
    assert first_d["verdict"] == "pass"
    assert client.post(f"/api/submissions/{first}/confirm", headers=h, json={"reply": "not_needed"}).json() == \
        {"review_status": "confirmed", "reply_status": "not_needed"}
    other = client.get("/api/programs/aim/teams", headers=h).json()[0]["id"]
    assert client.patch(f"/api/submissions/{second}", headers=h, json={"team_id": other}).json()["error"]["code"] == "TEAM_PROGRAM_MISMATCH"
    club_team = next(t["id"] for t in client.get("/api/programs/club/teams", headers=h).json() if t["name"] == "소인배")
    d = client.patch(f"/api/submissions/{second}", headers=h, json={"team_id": club_team}).json()
    assert d["team"]["match"] == "manual" and d["team"]["name"] == "소인배"
    t = client.get(f"/api/teams/{club_team}", headers=h).json()
    assert t["known_senders"] == ["student@jnu.ac.kr"] and t["submissions"][0]["id"] == second
    assert client.put(f"/api/teams/{club_team}/aliases", headers=h, json={"aliases": ["소인", " 소인 "]}).json()["aliases"] == ["소인"]
    assert client.post(f"/api/submissions/{second}/rerun", headers=h).status_code == 202
    d = client.get(f"/api/submissions/{second}", headers=h).json()
    assert d["processing_status"] == "done" and d["team"]["name"] == "소인배"  # 담당자 지정 팀은 다시 검수해도 유지
    lst = client.get("/api/programs/club/submissions", headers=h, params={"verdict": "reject"}).json()
    assert [i["id"] for i in lst["items"]] == [second]


def test_no_attachment_and_unassigned_program(env):
    client, _ = env
    h = login(client)
    r = client.post("/api/dev/intake", headers=h, data={"subject": "회의비 제출합니다", "mailbox": "club_manager"})
    sid = r.json()["id"]
    d = client.get(f"/api/submissions/{sid}", headers=h).json()
    assert d["program"] is None and d["verdict"] == "reject" and d["checks"][0]["check_id"] == "R01"  # 첨부 없음은 부적합
    assert sid in [i["id"] for i in client.get("/api/programs/unassigned/submissions", headers=h).json()["items"]]
    hw = login(client, "wemeet-manager")
    assert client.get(f"/api/submissions/{sid}", headers=hw).status_code == 403
    d = client.patch(f"/api/submissions/{sid}", headers=h, json={"program": "aim"}).json()
    assert d["program"] == "aim"


def test_rules(env):
    client, _ = env
    h = login(client)
    r = client.get("/api/programs/club/rules", headers=h).json()
    assert r["status"] == "confirmed" and len([c for c in r["conditions"] if c["enabled"]]) == 18  # v2: R21 품목 표기
    assert [c["id"] for c in r["conditions"] if not c["enabled"]] == ["R18", "R19", "R20"]
    assert "임시" in client.get("/api/programs/aim/rules", headers=h).json()["note"]


def test_mail_webhook(env):
    client, cases = env
    case, path = cases[("A17_결제자서명누락", "pdf")]
    msg = EmailMessage()
    msg["From"] = "자동 수집 <relay@jnu.ac.kr>"
    msg["To"] = "submit@jnuai-meetingfee.com"
    msg["Subject"] = "[수집] [동아리] 테라바이트 회의비"
    msg["Message-ID"] = "<abc123@jnu.ac.kr>"
    msg.set_content("FROM: 김학생 <kim@jnu.ac.kr>\nTO: 동아리 담당자 <club@jnu.ac.kr>\nRECEIVED: 2026-10-16T10:00:00+09:00\n\n제출합니다")
    msg.add_attachment(path.read_bytes(), maintype="application", subtype="pdf", filename=path.name)
    raw = msg.as_bytes()
    assert client.post("/api/intake/mail", content=raw, headers={"X-Intake-Secret": "wrong"}).status_code == 401
    r = client.post("/api/intake/mail", content=raw, headers={"X-Intake-Secret": "hook-secret"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert client.post("/api/intake/mail", content=raw, headers={"X-Intake-Secret": "hook-secret"}).json() == {"id": sid, "duplicate": True, "skipped": None}
    from app.config import get_settings

    assert (get_settings().data_dir / "raw" / f"{sid}.eml").read_bytes() == raw  # 원본 메일 보관
    d = client.get(f"/api/submissions/{sid}", headers=login(client)).json()
    assert d["sender"] == {"name": "김학생", "email": "kim@jnu.ac.kr"} and d["mail"]["subject"] == "[동아리] 테라바이트 회의비"
    assert d["received_at"] == "2026-10-16T10:00:00+09:00" and d["verdict"] == "needs_fix"
    assert [c["check_id"] for c in d["checks"] if c["result"] == "unmet"] == ["R16"]


def test_non_form_attachment_is_dropped(env):
    """회의비 증빙 양식이 아닌 첨부만 있으면 저장하지 않는다."""
    client, _ = env
    h = login(client)
    import io

    from docx import Document as Docx

    buf = io.BytesIO()
    d = Docx()
    d.add_paragraph("동아리 활동 계획서: 다음 학기 일정")
    d.save(buf)
    r = client.post("/api/dev/intake", headers=h, data={"subject": "[동아리] 테라바이트 계획서"},
                    files=[("files", ("계획서.docx", buf.getvalue()))])
    assert r.status_code == 201 and r.json()["id"] is None and "양식이 아닌" in r.json()["skipped"]


def test_mail_before_intake_since_is_skipped(env):
    client, cases = env
    from datetime import datetime

    from app.config import get_settings

    _, path = cases[("A01_정상", "hwp")]
    msg = EmailMessage()
    msg["Subject"], msg["Message-ID"] = "[수집] 예전 메일", "<old1@jnu.ac.kr>"
    msg.set_content("FROM: 김학생 <kim@jnu.ac.kr>\nRECEIVED: 2026-10-30T12:29:00+09:00\n")
    msg.add_attachment(path.read_bytes(), maintype="application", subtype="octet-stream", filename=path.name)
    s = get_settings()
    s.intake_since = datetime(2026, 10, 30, 12, 30)
    try:
        r = client.post("/api/intake/mail", content=msg.as_bytes(), headers={"X-Intake-Secret": "hook-secret"}).json()
    finally:
        s.intake_since = None
    assert r["id"] is None and "이전 메일" in r["skipped"]


def test_form_check_item(env):
    """F00 양식 확인이 맨 앞에 오고, 가상 회의록(실제 별첨 1-1 양식 기반)은 일치로 나온다."""
    client, cases = env
    h = login(client)
    sid = upload(client, h, cases[("A04_20시이후", "hwp")][1])
    d = client.get(f"/api/submissions/{sid}", headers=h).json()
    f00 = next(c for c in d["checks"] if c["check_id"] == "F00")
    assert f00["result"] == "met" and "100%" in f00["message"]
