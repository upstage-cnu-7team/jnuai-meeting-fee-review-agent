"""기준 설정(RuleAgent 역할): 지침+양식에서 Upstage가 뽑은 값(guide.hwp.ie.json) → 판정 조건 초안 yaml.

조건 유형(type)은 코드가 아는 것만 쓴다. 숫자·시각·지역 같은 기준값은 추출값에서 채우고, 어느 추출 항목에서 왔는지(source)를 남긴다.
담당자가 이 파일을 검토·수정·추가한 뒤 status를 confirmed로 바꾸면 판정에 쓴다.

    python experiments/aicollege_upstage/build_rules.py guide.hwp.ie.json rules/aicollege_club.yaml
"""
import json
import sys
from pathlib import Path

import yaml


def build(ie: dict) -> dict:
    R = []

    def add(cid, name, type_, by, severity, source, **params):
        R.append({"id": cid, "name": name, "type": type_, "by": by, "severity": severity,
                  "params": params, "source": {k: ie.get(k) for k in source}, "origin": "지침 추출"})

    add("R01", "영수증 첨부, 금액 > 0", "receipt_attached", "코드", "보완필요", ["meeting_required_documents"])
    add("R02", "연구비카드 매출전표 (간이·현금영수증 불가)", "card_slip", "코드", "부적합",
        ["meeting_payment_method", "receipt_rule"], card_word=ie.get("meeting_payment_method") or "연구비카드",
        reject_words=["간이영수증", "현금영수증", "현금"])
    add("R03", "승인번호 표기", "approval_number", "코드", "보완필요", ["receipt_rule"])
    add("R04", "회의일 = 영수증 거래일", "same_date", "코드", "부적합", ["meal_payment_rule", "snack_payment_rule"])
    add("R05", "평일 사용 (주말 불가)", "weekday_only", "코드", "부적합", ["meeting_frequency", "form_notice"])
    add("R06", f"{ie.get('meeting_pay_before_time')} 이전 결제", "pay_before", "코드", "부적합",
        ["meeting_pay_before_time"], time=ie.get("meeting_pay_before_time"))
    add("R07", "술집·주류 결제 불가", "no_alcohol", "Solar", "부적합", ["meeting_prohibited_merchants", "form_notice"],
        words=ie.get("meeting_prohibited_merchants"))
    add("R08", f"1인당 {int(ie.get('meeting_per_person_limit') or 0):,}원 이내", "per_person_limit", "코드", "부적합",
        ["meeting_per_person_limit"], limit=ie.get("meeting_per_person_limit"))
    add("R09", "식비는 회의 후 / 다과비는 회의 전 정해진 시간 안에 결제", "pay_window", "Solar+코드", "부적합",
        ["meal_payment_rule", "meal_minutes_after_meeting", "snack_payment_rule", "snack_minutes_before_meeting"],
        meal_after=ie.get("meal_minutes_after_meeting"), snack_before=ie.get("snack_minutes_before_meeting"))
    add("R10", f"회의 {int(ie.get('min_meeting_minutes') or 0)}분 이상 운영", "min_meeting", "코드", "부적합",
        ["min_meeting_minutes"], minutes=ie.get("min_meeting_minutes"))
    add("R11", f"가맹점 {ie.get('allowed_region')} (불가: {', '.join(ie.get('prohibited_regions') or [])})", "region", "코드", "부적합",
        ["allowed_region", "prohibited_regions"], allowed=ie.get("allowed_region"), prohibited=ie.get("prohibited_regions"))
    add("R12", "회의 장소 카페·식당 불가 (연구실·회의실·실험실 등)", "place_not_food", "Solar", "부적합",
        ["form_place_guide", "form_notice"])
    add("R13", "회의내용 구체적·상세", "content_specific", "Solar", "보완필요", ["form_notice"])
    add("R14", "참석자 전원 서명 (자필·전자, 워드 작성 불가)", "attendee_signatures", "Extract+코드", "보완필요",
        ["form_signature_guide", "meeting_required_documents"])
    add("R15", "사용 비용 칸 = 영수증 합계", "amount_matches", "코드", "보완필요", ["form_fields"])
    add("R16", "결제자 소속·이름·서명", "payer_signature", "Extract+코드", "보완필요", ["form_fields"])
    add("R17", "사용 후 1주일 이내 제출", "submit_within_days", "코드(접수 일시)", "보완필요", ["meeting_submit_deadline"], days=7)
    add("R18", "1회/1일 사용", "once_per_day", "코드(팀 이력)", "부적합", ["meeting_frequency"])
    add("R19", "교과목 수강 시간 내 회의 불가", "manual", "사람 확인", "확인필요", ["class_time_rule"])
    add("R20", "카드 사용 1일 전 예약·반납", "manual", "사람 확인", "확인필요", ["meeting_card_reservation"])
    return {
        "program": "인공지능혁신융합대학사업단 동아리 회의비",
        "status": "draft",  # 담당자 확인 후 confirmed
        "source_file": "별첨1+1-1_회의비_지침과_양식.hwp",
        "extracted_by": "Upstage information-extract",
        "conditions": R,
        "staff_added": [],  # 담당자 의견으로 추가하는 조건 (origin: 담당자)
    }


if __name__ == "__main__":
    ie = json.load(open(sys.argv[1]))
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(build(ie), allow_unicode=True, sort_keys=False, width=200), encoding="utf-8")
    print(out)
