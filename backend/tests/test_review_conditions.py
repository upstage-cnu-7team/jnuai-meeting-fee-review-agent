"""조건 판정·종합 판정·회신 초안 단위 시험 (Upstage 호출 없음)."""
from __future__ import annotations

import copy
from datetime import datetime

import pytest

from app.review import conditions as C
from app.review.draft import make_reply
from app.review.pipeline import RECEIPT_FIELDS, extracted_view, mask_card, mask_student_id, receipt_missing
from app.review.verdict import verdict
from app.seed import RULES_DIR, rule_set_from_yaml

RS = rule_set_from_yaml(RULES_DIR / "aicollege_club.yaml", "club")

IE = {
    "team_name": "코딩하는감자들", "meeting_title": "MVP 범위 확정", "meeting_date": "2026-10-14", "start_time": "17:00", "end_time": "18:30",
    "place": "공과대학 7호관 501호", "content": "1. 인터뷰 결과 공유\n2. MVP 범위 확정\n3. 일정 결정",
    "attendees": [{"affiliation": "인공지능학부", "student_id": "202400001", "name": n, "has_signature": False} for n in ("김가온", "이나래", "박다솜")],
    "used_amount": 60000, "payer_affiliation": "인공지능학부", "payer_name": "김가온", "payer_has_signature": False,
    "receipt_attached": True, "receipt_type": "신용카드 매출전표", "merchant_name": "가온분식", "merchant_address": "광주광역시 북구 용봉로 0",
    "card_type": "가상은행 연구비카드", "card_number": "5310-12**-****-3456", "approval_number": "30012345",
    "transaction_datetime": "2026-10-14 18:42", "receipt_items": [{"name": "김밥", "quantity": 3, "amount": 60000}], "receipt_total": 60000,
}
SJ = {k: {"decision": "ok", "reason": "문제 없음"} for k in ("place", "alcohol", "content")} | {"expense_kind": {"kind": "식비", "reason": "식사"}}
MARKS = {"attendee_signed": {"김가온": True, "이나래": True, "박다솜": True}, "payer_signed": True, "receipt_image": True}
SUBMITTED = datetime(2026, 10, 16, 10, 0)


def run(ie=None, sj=None, marks=None, submitted=SUBMITTED):
    checks = C.judge(ie or IE, sj or SJ, marks or MARKS, submitted, RS.conditions, RS.removed)
    return {c["check_id"]: c for c in checks}, checks


def with_ie(**kw):
    ie = copy.deepcopy(IE)
    ie.update(kw)
    return ie


def test_baseline_all_met():
    by, checks = run()
    assert {k for k, c in by.items() if c["result"] != "met"} == {"R18", "R19", "R20"}
    assert verdict(checks) == "pass"


AMOUNT = next(c["id"] for c in RS.conditions if c["type"] == "amount_matches")
LIMIT = next(c["id"] for c in RS.conditions if c["type"] == "per_person_limit")


@pytest.mark.parametrize("kw", [
    pytest.param({"receipt_total": 62000, "receipt_discount": 2000, "receipt_paid": 60000}, id="합계·할인·결제금액"),
    pytest.param({"receipt_total": 62000, "receipt_discount": 2000}, id="결제금액 없음"),
    pytest.param({"receipt_total": 62000, "receipt_discount": -2000}, id="할인이 음수로 추출"),
    pytest.param({"receipt_total": 62000, "receipt_paid": 60000}, id="할인 칸 없음"),
    pytest.param({"receipt_total": None, "receipt_paid": 60000}, id="합계 없이 결제금액만"),
])
def test_discounted_receipt_uses_paid_amount(kw):
    """할인이 있으면 할인 뒤 실제 결제금액을 사용 비용과 맞춘다 (소인배 위밋 제출, 2026-11-02)."""
    by, _ = run(ie=with_ie(**kw))
    assert by[AMOUNT]["result"] == "met"
    assert "60,000" in by[AMOUNT]["evidence"]["found"]


def test_discount_shows_how_amount_was_computed():
    by, _ = run(ie=with_ie(receipt_total=62000, receipt_discount=2000, receipt_paid=60000))
    assert "합계 62,000 − 할인 2,000" in by[AMOUNT]["evidence"]["found"]


def test_per_person_limit_uses_paid_amount():
    """할인 전 합계로는 1인당 한도를 넘어도 실제 결제금액이 한도 안이면 충족."""
    by, _ = run(ie=with_ie(receipt_total=66000, receipt_discount=6000, receipt_paid=60000, used_amount=60000))
    assert by[LIMIT]["result"] == "met"


def test_still_unmet_when_used_amount_matches_neither():
    by, _ = run(ie=with_ie(receipt_total=62000, receipt_discount=2000, receipt_paid=60000, used_amount=55000))
    assert by[AMOUNT]["result"] == "unmet"


@pytest.mark.parametrize("kw", [
    pytest.param({"receipt_total": 62000, "receipt_discount": 2000, "receipt_paid": 62000, "used_amount": 60000}, id="결제금액이 합계와 같게 추출"),
    pytest.param({"receipt_total": 60000, "receipt_discount": 2000, "used_amount": 60000}, id="합계가 이미 할인 뒤일 수 있음"),
])
def test_ambiguous_discount_goes_to_review(kw):
    """할인 전 금액인지 뒤 금액인지 단정할 수 없으면 학생에게 지적하지 않고 담당자가 본다."""
    by, _ = run(ie=with_ie(**kw))
    assert by[AMOUNT]["result"] == "review"


def test_discount_not_smaller_than_total_is_ignored():
    by, _ = run(ie=with_ie(receipt_total=60000, receipt_discount=60000))
    assert by[AMOUNT]["result"] == "met"


def test_retry_keeps_discount_fields_and_paid_only_is_not_missing():
    assert {"receipt_discount", "receipt_paid"} <= set(RECEIPT_FIELDS)
    assert not receipt_missing({"receipt_paid": 60000, "merchant_name": "가온분식"})


def test_extracted_view_total_is_paid_amount():
    view = extracted_view(with_ie(receipt_total=62000, receipt_discount=2000, receipt_paid=60000), MARKS)
    assert view["receipt"]["total"] == 60000


def test_receipt_photo_unreadable_asks_resubmit():
    """영수증 사진은 붙었는데 글자를 못 읽으면 추측하지 않고 학생에게 다시 제출을 요청한다(보완필요)."""
    ie = with_ie(receipt_total=None, merchant_name="", transaction_datetime="", receipt_attached=True)
    by, checks = run(ie=ie)
    assert by["R01"]["result"] == "unmet" and "다시 제출" in by["R01"]["message"]
    assert verdict(checks) == "needs_fix"
    reply = make_reply(checks, "제목")
    assert "다시 제출" in reply["body"] and "R15" not in reply["body"]


def test_no_receipt_is_unmet():
    ie = with_ie(receipt_total=None, merchant_name="", transaction_datetime="")
    by, checks = run(ie=ie, marks={**MARKS, "receipt_image": False})
    assert by["R01"]["result"] == "unmet" and "영수증 미첨부" in by["R01"]["message"]
    # 영수증 자체가 없으면 영수증에 기대는 조건(카드·승인번호·금액·지역 등)은 띄우지 않는다
    receipt_types = {"card_slip", "approval_number", "same_date", "amount_matches", "region", "per_person_limit"}
    types = {c["id"]: c["type"] for c in RS.conditions}
    assert not [c for c in checks if types.get(c["check_id"]) in receipt_types]
    assert {"R10", "R13", "R14", "R16"} <= set(by)  # 회의 시간·내용·서명 조건은 그대로
    assert make_reply(checks, "제목")["body"].count("영수증") >= 1


@pytest.mark.parametrize("submitted,expected", [(datetime(2026, 10, 21, 17, 59), "met"), (datetime(2026, 10, 21, 18, 0), "unmet")])
def test_r17_deadline_is_7th_day_1800(submitted, expected):
    by, _ = run(submitted=submitted)
    assert by["R17"]["result"] == expected


def test_weekend_and_late_payment_reject():
    by, checks = run(ie=with_ie(meeting_date="2026-10-17", transaction_datetime="2026-10-17 20:25", start_time="18:30", end_time="20:00"))
    assert by["R05"]["result"] == "unmet" and by["R06"]["result"] == "unmet"
    assert verdict(checks) == "reject"


def test_typed_signature_is_unmet_and_goes_to_reply():
    by, checks = run(marks={**MARKS, "attendee_signed": {"김가온": True, "이나래": True, "박다솜": "typed"}})
    assert by["R14"]["result"] == "unmet" and "워드" in by["R14"]["message"]
    reply = make_reply(checks, "[동아리] 감자들 회의비", "코딩하는감자들")
    assert reply["subject"].startswith("RE: ")
    assert "박다솜" in reply["body"] and verdict(checks) == "needs_fix"


def test_review_goes_to_internal_notes_not_body():
    sj = SJ | {"expense_kind": {"kind": "불명", "reason": "품목이 애매함"}}
    by, checks = run(ie=with_ie(receipt_items=[{"name": "모둠세트", "quantity": 1, "amount": 60000}]), sj=sj)
    assert by["R09"]["result"] == "review" and verdict(checks) == "review"
    reply = make_reply(checks, "제목")
    assert "R09" not in reply["body"] and any(n.startswith("R09") for n in reply["internal_notes"])


def test_region_outside_bukgu():
    by, _ = run(ie=with_ie(merchant_address="광주광역시 동구 제봉로 0"))
    assert by["R11"]["result"] == "unmet"
    by, _ = run(ie=with_ie(merchant_address="전라남도 담양군 담양읍"))
    assert by["R11"]["result"] == "unmet"  # 다른 시·도가 분명하면 미충족
    by, _ = run(ie=with_ie(merchant_address="광주 북구 용봉로 0"))
    assert by["R11"]["result"] == "met"  # 줄임 표기
    by, _ = run(ie=with_ie(merchant_address="서울특별시 강남구 테헤란로 0"))
    assert by["R11"]["result"] == "unmet" and "강남구" in by["R11"]["message"]
    by, _ = run(ie=with_ie(merchant_address="용봉로 0"))
    assert by["R11"]["result"] == "review"  # 시·구가 없음
    by, _ = run(ie=with_ie(merchant_address="전남광주통합특별시 북구 서하로 360"))
    assert by["R11"]["result"] == "met"  # 통합 시 이름 (2026-11-03 EPOCH)
    by, _ = run(ie=with_ie(merchant_address="북구 호동로 9-1 1층"))
    assert by["R11"]["result"] == "review" and "시 이름" in by["R11"]["message"]  # 시 이름 없는 북구는 다시 확인 (2026-11-04)
    by, _ = run(ie=with_ie(merchant_address="전남광주통합특별시 나주시 빛가람로 0"))
    assert by["R11"]["result"] == "review"


def test_unreadable_receipt_does_not_pile_up_unmet():
    ie = with_ie(receipt_total=None, merchant_name="", transaction_datetime="", approval_number="", receipt_type="", card_type="")
    by, checks = run(ie=ie)
    assert [c["check_id"] for c in checks if c["result"] == "unmet"] == ["R01"]
    assert "판정 보류" in by["R15"]["message"] and by["R15"]["result"] == "review"


def test_expense_kind_by_item_words():
    snack = with_ie(receipt_items=[{"name": "아메리카노", "quantity": 4, "amount": 12000}, {"name": "샌드위치", "quantity": 2, "amount": 12000}],
                    transaction_datetime="2026-10-14 16:30")
    by, _ = run(ie=snack, sj=SJ | {"expense_kind": {"kind": "식비", "reason": "샌드위치"}})
    assert by["R09"]["result"] == "review"  # 단어로는 다과비, AI는 식비 → 엇갈림
    by, _ = run(ie=snack, sj=SJ | {"expense_kind": {"kind": "다과비", "reason": "간식"}})
    assert by["R09"]["result"] == "met"


def test_masking():
    assert mask_student_id("202400001") == "2024*****"
    assert mask_card("9410-1234-5678-1234") == "9410-****-****-1234"
    view = extracted_view(IE, MARKS)
    assert view["attendees"][0]["student_id"].endswith("*") and view["attendees"][0]["has_signature"] is True
    assert view["receipt"]["transaction_datetime"] == "2026-10-14T18:42:00+09:00"


def test_keyword_guard_beats_solar_ok():
    """장소·가맹점·품목 글자로 분명한 위반은 Solar가 ok를 줘도 미충족."""
    by, _ = run(ie=with_ie(place="가온카페 용봉점 2층"))
    assert by["R12"]["result"] == "unmet" and "카페" in by["R12"]["message"]
    by, _ = run(ie=with_ie(merchant_name="가온호프 용봉점"))
    assert by["R07"]["result"] == "unmet"
    # 품목에만 술 글자가 있으면 확인필요 + 품목 이름 (2026-11-04 AiBara '와인무화과휘낭이')
    by, _ = run(ie=with_ie(receipt_items=[{"name": "와인무화과휘낭이", "quantity": 1, "amount": 2700}]))
    assert by["R07"]["result"] == "review" and "와인무화과휘낭이" in by["R07"]["message"]


def test_campus_place_beats_solar():
    """Solar가 '7호관 스터디라운지'를 카페로 봐도 학교 안 공간 단어가 있으면 충족 (2026-11-02 전자파)."""
    place = next(c["id"] for c in RS.conditions if c["type"] == "place_not_food")
    sj = {**SJ, "place": {"decision": "violation", "reason": "카페"}}
    by, _ = run(ie=with_ie(place="전남대학교 7호관 스터디라운지"), sj=sj)
    assert by[place]["result"] == "met"
    by, _ = run(ie=with_ie(place="7호관 앞 카페"), sj=sj)
    assert by[place]["result"] == "unmet"


def test_no_receipt_is_always_needs_fix():
    """영수증 미첨부는 사용 비용 칸이 비었든 아니든 보완필요 (2026-11-02 종희)."""
    ie = with_ie(receipt_total=None, merchant_name="", transaction_datetime="", used_amount=None)
    by, checks = run(ie=ie, marks={**MARKS, "receipt_image": False})
    assert "영수증 미첨부" in by["R01"]["message"] and verdict(checks) == "needs_fix"
    _, checks = run(ie=with_ie(receipt_total=None, merchant_name="", transaction_datetime=""), marks={**MARKS, "receipt_image": False})
    assert verdict(checks) == "needs_fix"
    # 사용 비용 0원 회의록도 보완필요 (2026-11-03 종희, VCCC 10.27)
    by, checks = run(ie=with_ie(receipt_total=None, merchant_name="", transaction_datetime="", used_amount=0), marks={**MARKS, "receipt_image": False})
    assert "0원" in by["R01"]["message"] and verdict(checks) == "needs_fix"


def test_no_attachment_reply():
    """첨부파일이 아예 없으면 부적합, 회신은 첨부 안내 한 가지 (2026-11-02)."""
    from app.graph.review_graph import NO_ATTACHMENT
    check = {"check_id": "R01", "name": "증빙 첨부파일", "by": "code", "severity": "reject", "result": "unmet", "message": NO_ATTACHMENT,
             "evidence": {"field": "attachments", "found": "첨부 0개"}}
    assert verdict([check]) == "reject"
    body = make_reply([check], "회의비 증빙", "마니오")["body"]
    assert "마니오 팀" in body and "첨부파일이 첨부되지 않았습니다" in body and "■" not in body


def test_spaced_approval_number_is_met():
    """'7950 9130'처럼 띄어 찍힌 승인번호도 충족 (2026-11-02 NoBrains)."""
    approval = next(c["id"] for c in RS.conditions if c["type"] == "approval_number")
    by, _ = run(ie=with_ie(approval_number="7950 9130"))
    assert by[approval]["result"] == "met"


def test_masked_card_number_prefix_is_research_card():
    """카드사 매출전표의 '533014******0110'(앞 6자리만 보임)도 연구비카드 (2026-11-02 성장통 위밋)."""
    card = next(c["id"] for c in RS.conditions if c["type"] == "card_slip")
    by, _ = run(ie=with_ie(card_type="비씨카드사", card_number="533014******0110"))
    assert by[card]["result"] == "met"
    by, _ = run(ie=with_ie(card_type="국민카드", card_number="940312******1234"))
    assert by[card]["result"] == "unmet"


def test_no_receipt_items_is_review():
    """영수증에 메뉴·품목이 없으면 확인필요, 학생 회신에는 안 들어감 (2026-11-02)."""
    items = next(c["id"] for c in RS.conditions if c["type"] == "receipt_items")
    by, checks = run(ie=with_ie(receipt_items=[]))
    assert by[items]["result"] == "review"
    assert "품목" not in make_reply(checks, "제목")["body"]
    by, _ = run()
    assert by[items]["result"] == "met"
