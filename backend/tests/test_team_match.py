import pytest
"""프로그램·팀 정하기: 별첨 제목 단어(캡스톤·동아리·WE-Meet), 제목 없는 양식은 AIM·해커톤 팀명, 겹치는 팀(테라바이트)은 팀원 명단."""
from app.review.team_match import TeamCandidate, decide

AIM = [TeamCandidate("t_aim_001", "AIBara", [], False), TeamCandidate("t_aim_003", "테라바이트", [], True, ["김가온", "이나래"])]
HACK = [TeamCandidate("t_hackathon_003", "테라바이트", [], True, ["박다솜", "최라온"]), TeamCandidate("t_hackathon_004", "마니오", [], False)]
CLUB = [TeamCandidate("t_club_030", "테라바이트", [], True)]
TEAMS = {"aim": AIM, "hackathon": HACK, "club": CLUB, "wemeet": [], "capstone": []}
NO_TITLE = "[별첨 1-1.] 회의비 증빙\n팀명 ..."


def test_title_words():
    d = decide("[별첨 1-1.] 동아리 회의비 지출 증빙", "club_manager", "", "테라바이트", [], TEAMS)
    assert (d.program, d.team_id) == ("club", "t_club_030")
    assert decide("[별첨 1-1.] WE-Meet 회의비 지출 증빙", "wemeet_manager", "", "x", [], TEAMS).program == "wemeet"
    assert decide("[별첨 1-1.] 캡스톤디자인 회의비 지출 증빙", "wemeet_manager", "", "x", [], TEAMS).program == "capstone"


def test_no_title_team_only_in_one_program():
    d = decide(NO_TITLE, "club_manager", "", "마니오", [], TEAMS)
    assert (d.program, d.team_id) == ("hackathon", "t_hackathon_004")
    d = decide(NO_TITLE, "club_manager", "", "AIBara", [], TEAMS)
    assert (d.program, d.team_id) == ("aim", "t_aim_001")


def test_terabyte_by_roster():
    d = decide(NO_TITLE, "club_manager", "", "테라바이트", ["박다솜", "최라온", "김새봄"], TEAMS)
    assert (d.program, d.team_id) == ("hackathon", "t_hackathon_003") and "명단" in d.program_reason
    d = decide(NO_TITLE, "club_manager", "", "테라바이트", ["김가온"], TEAMS)
    assert d.program == "aim"


def test_terabyte_unresolved_shows_alert():
    d = decide(NO_TITLE, "club_manager", "", "테라바이트", ["모르는사람"], TEAMS)
    assert d.program is None and d.team_id is None and "테라바이트" in d.alert
    empty = {**TEAMS, "aim": [TeamCandidate("t_aim_003", "테라바이트", [], True)], "hackathon": [TeamCandidate("t_hackathon_003", "테라바이트", [], True)]}
    d = decide(NO_TITLE, "club_manager", "", "테라바이트", ["김가온"], empty)
    assert d.program is None and "명단이 아직 등록되지" in d.alert


def test_no_title_no_team():
    d = decide(NO_TITLE, "club_manager", "", "없는팀", [], TEAMS)
    assert d.program is None and d.alert


def test_form_title_beats_mailbox():
    """위밋 메일함으로 왔어도 회의록이 동아리 양식이면 동아리로 정하고 알린다."""
    d = decide("[별첨 1-1.] 동아리 회의비 지출 증빙", "wemeet_manager", "[위밋] 테라바이트 회의비", "테라바이트", [], TEAMS)
    assert d.program == "club" and d.team_id == "t_club_030" and "동아리 양식" in d.alert


def test_form_team_name_beats_mail_subject():
    """회의록 팀명이 팀 목록에 없으면 메일 제목의 팀명을 붙이지 않는다."""
    teams = {**TEAMS, "club": CLUB + [TeamCandidate("t_club_002", "AfterandAfter", [], False)]}
    d = decide("[별첨 1-1.] 동아리 회의비 지출 증빙", "club_manager", "[동아리] AfterandAfter 회의비", "코드메이트", [], teams)
    assert d.team_id is None and "코드메이트" in d.team_reason and "AfterandAfter" in d.alert


def test_mail_program_is_cross_checked_with_form():
    d = decide("[별첨 1-1.] 동아리 회의비 지출 증빙", "club_manager", "위밋 증빙 제출", "없는팀", [], TEAMS)
    assert d.program == "club" and "교차 확인" in d.alert


def test_form_team_name_wins_without_alert():
    """파일 이름·메일에 WE-Meet이 있어도 회의록 팀명 칸으로 팀을 찾으면 안내 없이 바로 분류 (2026-11-02 성장통)."""
    team = TEAMS["club"][0]
    d = decide("[별첨 1-1.] 동아리 회의비 지출 증빙", "club_manager", f"{team.name} 10.29_WE_Meet.hwp", team.name, [], TEAMS)
    assert d.program == "club" and d.team_id == team.id and not d.alert and "회의록 팀명으로 확정" in d.program_reason
    d = decide("[별첨 1-1.] WE-Meet 회의비 지출 증빙", "wemeet_manager", "we-meet 회의비", "x", [], TEAMS)
    assert d.program == "wemeet" and "표기 일치" in d.program_reason


def test_configured_terabyte_rosters():
    from app.review.team_match import _cfg

    if not any(t.get("members") for t in _cfg()["programs"]["aim"]):
        pytest.skip("공개본은 실제 팀원 명단을 비워 둠")

    teams = {}
    for program in ("aim", "hackathon"):
        row = next(t for t in _cfg()["programs"][program] if t["name"] == "테라바이트")
        assert len(row["members"]) == 4
        teams[program] = [TeamCandidate(program, row["name"], [], True, row["members"])]
        d = decide(NO_TITLE, "club_manager", "", "테라바이트", row["members"], {**TEAMS, **teams})
        assert d.program == program
    mixed = teams["aim"][0].members[:1] + teams["hackathon"][0].members[:1]
    d = decide(NO_TITLE, "club_manager", "", "테라바이트", mixed, teams)
    assert d.program is None and "함께" in d.alert


def test_no_attachment_mail_team_name_decides_program():
    """첨부가 없어도 메일 제목·본문의 팀명으로 프로그램·팀을 정한다 (2026-11-02)."""
    d = decide("", "club_manager", "마니오 회의비 증빙 접수합니다", None, [], TEAMS)
    assert d.program == "hackathon" and d.team_id == "t_hackathon_004"
    d = decide("", None, "아무 내용 없음", None, [], TEAMS)
    assert d.program is None
