from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.mail import intake
from app.review import readers


@pytest.fixture
def raw():
    message = EmailMessage()
    message["From"] = "test@example.invalid"
    message["Subject"] = "가상 메일 제목"
    message.set_content("가상 메일 본문")
    message.add_attachment(b"unreadable", maintype="application", subtype="octet-stream", filename="test.hwp")
    return message.as_bytes()


FAKE_DB = SimpleNamespace(scalar=lambda *_: None, commit=lambda: None, scalars=lambda _: [])


def held_env(monkeypatch):
    from app import worker

    sub, queued = SimpleNamespace(id="s_held", processing_status="queued", processing_error=None), []
    monkeypatch.setattr(worker, "create_submission", lambda db, **values: sub)
    monkeypatch.setattr(worker, "enqueue", queued.append)
    return sub, queued


def test_rejected_mail_is_staged_before_screen_then_deleted(tmp_path, monkeypatch, raw):
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "intake_since", None)

    def screen(files):
        staged = list((tmp_path / "intake_pending").glob("*.eml"))
        assert len(staged) == 1 and staged[0].read_bytes() == raw
        assert staged[0].stat().st_mode & 0o777 == 0o600
        return "not_form", "양식 아님"

    monkeypatch.setattr(readers, "screen_result", screen)
    sub, queued = held_env(monkeypatch)
    r = intake.intake_raw(FAKE_DB, raw)
    assert r.skipped == "양식 아님" and r.id == sub.id and not queued
    # 버리지 않고 '양식 검토 대기'로 남긴다 (종희가 확인 후 지움, 2026-11-02)
    assert sub.processing_error == intake.HELD_PREFIX + "양식 아님" and sub.processing_status == "failed"
    assert not list((tmp_path / "intake_pending").iterdir())
    assert (tmp_path / "raw" / f"{sub.id}.eml").read_bytes() == raw


def test_failure_preserves_staged_original(tmp_path, monkeypatch, raw):
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)

    def fail(_):
        raise ValueError("synthetic failure")

    monkeypatch.setattr(intake, "parse_mail", fail)
    with pytest.raises(ValueError):
        intake.intake_raw(None, raw)
    assert [p.read_bytes() for p in (tmp_path / "intake_pending").iterdir()] == [raw]


def test_review_mode_keeps_rejected_mail_for_human_comparison(tmp_path, monkeypatch, raw):
    import json

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "intake_since", None)
    monkeypatch.setattr(get_settings(), "intake_review_mode", True)
    monkeypatch.setattr(readers, "screen_result", lambda _: ("not_form", "양식 아님"))
    held_env(monkeypatch)
    assert intake.intake_raw(FAKE_DB, raw).skipped
    files = list((tmp_path / "intake_review").glob("*.eml"))
    assert len(files) == 1 and files[0].read_bytes() == raw
    assert json.loads(files[0].with_suffix(".json").read_text())["skipped"] == "양식 아님"
    assert not list((tmp_path / "intake_pending").iterdir())


def test_unreadable_attachment_is_kept_for_review(tmp_path, monkeypatch, raw):
    from app import worker

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "intake_since", None)
    assert readers.screen_result([("test.hwp", b"unreadable")]) == ("unverified", None)
    seen = []
    monkeypatch.setattr(worker, "create_submission", lambda db, **values: SimpleNamespace(id="test_submission"))
    monkeypatch.setattr(worker, "enqueue", seen.append)
    result = intake.intake_raw(None, raw)
    assert result.id == "test_submission" and seen == [result.id]
    assert (tmp_path / "raw/test_submission.eml").read_bytes() == raw
    assert not list((tmp_path / "intake_pending").iterdir())


def test_mail_without_form_or_team_name_is_not_project_mail():
    """양식 첨부도 팀명도 없는 메일(중계 계정 개인 메일·일정 초대)은 받지 않는다 (2026-11-02)."""
    teams = [SimpleNamespace(id="t1", name="성장통", aliases=[], strict=False, members=[])]
    db = SimpleNamespace(scalars=lambda _: teams)
    mail = {"subject": "회의 초대", "body_text": "다음 주 일정입니다", "files": [("invite.ics", b"BEGIN:VCALENDAR")]}
    assert not intake._mentions_team(db, mail)
    assert intake._mentions_team(db, {**mail, "subject": "성장통 회의비 증빙"})
    assert intake._mentions_team(db, {**mail, "files": [("성장통_회의록.jpg", b"")]})


def test_no_attachment_without_meeting_words_is_held(tmp_path, monkeypatch):
    """첨부 없고 '회의·증빙·영수증'이 없는 메일(멘토링 일정 공유)은 검수하지 않고 양식 검토 대기 (2026-11-02)."""
    from email.message import EmailMessage

    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)
    monkeypatch.setattr(get_settings(), "intake_since", None)
    teams = [SimpleNamespace(id="t1", name="NoBrains", aliases=[], strict=False, members=[])]
    db = SimpleNamespace(scalar=lambda *_: None, commit=lambda: None, scalars=lambda _: teams)
    for subject, body, held in [("[WE-Meet] 멘토링 일정 공유 - NoBrains 팀", "안녕하세요. NoBrains 팀입니다.", True),
                                ("[위밋 팀 NoBrains] 4차 멘토링 일정 공유", "회의록은 멘토님마다 각자 작성합니다.", True),  # METRO 사례
                                ("NoBrains 회의비 증빙 제출", "안녕하세요.", False)]:
        msg = EmailMessage()
        msg["From"], msg["Subject"] = "a@example.invalid", subject
        msg.set_content(body)
        sub, queued = held_env(monkeypatch)
        r = intake.intake_raw(db, msg.as_bytes())
        assert bool(r.skipped) == held and bool(queued) != held
