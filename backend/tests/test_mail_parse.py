"""수집 메일(Power Automate '[수집]') 해석: 메타 줄, 원본 Message-ID, 담당자 주소 → 메일함, 원문 본문."""
from email.message import EmailMessage

from app.config import get_settings
from app.mail.intake import parse_mail


def test_relay_mail_format():
    s = get_settings()
    old = s.manager_mailboxes
    s.manager_mailboxes = "club_manager=club@jnu.ac.kr,wemeet_manager=wemeet@jnu.ac.kr"
    try:
        msg = EmailMessage()
        msg["Subject"] = "[수집] [동아리] 성장통 10월 회의비"
        msg["Message-ID"] = "<relay-1@outlook>"
        msg.set_content("FROM: 김학생 <kim@jnu.ac.kr>\nTO: 동아리 담당자 <club@jnu.ac.kr>\nCC: \nRECEIVED: 2026-10-30T09:12:00Z\n"
                        "INTERNET_MSGID: <orig-1@jnu.ac.kr>\nMSGID: AAMkAD...\nATTACHMENTS: 0\nMATCHED: 성장통\n\n안녕하세요, 회의비 증빙 제출합니다.")
        m = parse_mail(msg.as_bytes())
    finally:
        s.manager_mailboxes = old
    assert m["subject"] == "[동아리] 성장통 10월 회의비"
    assert (m["sender_name"], m["sender_email"]) == ("김학생", "kim@jnu.ac.kr")
    assert m["message_id"] == "<orig-1@jnu.ac.kr>" and m["mailbox"] == "club_manager"
    assert m["received_at"].isoformat() == "2026-10-30T18:12:00"  # UTC → 한국 시간
    assert m["body_text"] == "안녕하세요, 회의비 증빙 제출합니다." and m["files"] == []


def test_double_base64_relay_attachment_recovers_original():
    import base64
    from pathlib import Path

    original = (Path(__file__).parents[1] / "forms/aicollege/별첨1-1_회의비_지출증빙_양식.hwp").read_bytes()
    for payload in (original, base64.b64encode(original)):
        msg = EmailMessage()
        msg.set_content("가상 메일")
        msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename="minutes.hwp")
        assert parse_mail(msg.as_bytes())["files"] == [("minutes.hwp", original)]


def test_plain_unknown_attachment_is_not_arbitrarily_decoded():
    msg = EmailMessage()
    msg.set_content("가상 메일")
    msg.add_attachment(b"YWJj", maintype="application", subtype="octet-stream", filename="unknown.txt")
    assert parse_mail(msg.as_bytes())["files"][0][1] == b"YWJj"
