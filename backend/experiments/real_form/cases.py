"""실제 사업단 양식(별첨 1-1 HWP)에 여러 내용을 채워 조건별로 걸러내는지 보는 실험 케이스 (2026-10-31).

기본 케이스는 실제 학생 제출본(성장통, 10/27)과 같은 모양으로 쓴다: 회의내용에 소제목·여러 줄, 양식 예시 표기의 회의일시.
각 케이스는 한 가지(또는 몇 가지)만 바꾸고, 그때 걸려야 하는 조건(expect: 미충족)을 적는다.
review: 확인필요로 나와야 하는 조건(있으면 함께 확인). 그 밖의 확인필요는 허용하되 결과표에 남긴다.
"""
from __future__ import annotations

import copy
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.aicollege_samples import BASE  # noqa: E402

CONTENT = [
    "1. 회의 주제",
    "일정 공유 서비스 MVP 범위 확정과 역할 분담",
    "2. 회의 내용",
    "지난주 사용자 인터뷰 12건을 정리해 일정 공유 기능 요구가 가장 많았음을 확인함. 알림 기능은 2순위로 정리함.",
    "MVP 범위를 일정 등록·공유·알림 3개 기능으로 확정하고, 화면 설계는 프론트 2명, API는 백엔드 2명이 맡기로 함.",
    "3. 향후 과제",
    "10월 28일까지 화면 설계 초안, 11월 4일까지 API 초안을 완성해 다음 회의에서 검토하기",
]


# 실제 연구비카드 영수증 표기 (성장통 제출본, 종희 확인): 카드번호 5330-1481…, 카드명 광주신용, 매입사 비씨카드
REAL_CARD = {"card_type": "광주신용 (매입사 비씨카드)", "card_no": "5330-1481-****-475*", "approval": "75971518"}


def case(name: str, note: str, expect=(), review=(), **change) -> dict:
    c = copy.deepcopy(BASE)
    c["content"] = list(CONTENT)
    c["team"] = "성장통"
    c["receipt"].update(REAL_CARD)
    for k, v in change.items():
        if k.startswith("r_"):
            if v is None:
                c["receipt"].pop(k[2:], None)
            else:
                c["receipt"][k[2:]] = v
        else:
            c[k] = v
    c.update(name=name, note=note, expect=sorted(expect), review=sorted(review))
    return c


A = BASE["attendees"]
SNACK = [("아메리카노", 4, 12000), ("쿠키", 4, 10000), ("샌드위치", 2, 12000)]
d = lambda m, dd: date(2026, m, dd)  # noqa: E731

CASES = [
    case("B00_정상", "실제 제출본 모양의 정상 케이스"),
    # R01 영수증
    case("R01a_영수증없음", "영수증 칸에 사진 없이 안내 글만", expect=["R01"], receipt=None),
    case("R01b_영수증흐림", "영수증 사진이 심하게 흐림 → 추측하지 말고 학생에게 다시 제출 요청", expect=["R01"], r_blur=True),
    # R02 영수증 종류
    case("R02a_간이영수증", "간이영수증, 카드·승인번호 없음", expect=["R02", "R03"], r_title="간이영수증", r_card_type=None, r_card_no=None, r_approval=None),
    case("R02b_현금영수증", "현금영수증(승인번호는 있음)", expect=["R02"], r_title="현금영수증", r_card_type=None, r_card_no=None),
    case("R02c_개인카드", "개인 신용카드로 결제 (카드명 국민카드, 번호도 연구비카드와 다름) → 부적합", expect=["R02"], r_card_type="KB국민카드",
         r_card_no="9410-12**-****-7788"),
    # R03 승인번호
    case("R03a_승인번호없음", "매출전표에 승인번호 줄 없음", expect=["R03"], r_approval=None),
    case("R03b_승인번호짧음", "승인번호 4자리", expect=["R03"], r_approval="1234"),
    # R04·R05 날짜·요일
    case("R04a_다음날결제", "회의 10/14, 결제 10/15 18:42", expect=["R04", "R09"], r_datetime="2026-10-15 18:42:10"),
    case("R05a_일요일", "일요일 회의·결제", expect=["R05"], date=d(10, 18), r_datetime="2026-10-18 18:42:10", submitted_at="2026-10-19 10:00"),
    # R06 20시
    case("R06a_20시정각", "18:30~19:30 회의, 20:00:00 결제 (20시 '이전'이 아님)", expect=["R06"], start="18:30", end="19:30", r_datetime="2026-10-14 20:00:00"),
    case("R06b_19시59분", "18:00~19:00 회의, 19:59 결제 (경계, 통과)", start="18:00", end="19:00", r_datetime="2026-10-14 19:59:00"),
    # R07 주류
    case("R07a_소주", "일반 식당이지만 품목에 소주", expect=["R07"], r_items=[("김치찌개", 4, 36000), ("소주", 4, 24000)]),
    case("R07b_포차상호", "가게 이름이 포차, 품목은 안주만", expect=["R07"], r_merchant="용봉 포차", r_items=[("닭볶음탕", 2, 40000), ("계란말이", 2, 20000)]),
    case("R07c_제로콜라", "음료는 제로콜라 (주류 아님, 통과)", r_items=[("김밥", 4, 16000), ("라면", 4, 24000), ("제로콜라", 4, 20000)]),
    # R08 1인당
    case("R08a_정확히2만원", "80,000원 ÷ 4명 = 20,000원 (경계, 통과)", amount="80,000",
         r_items=[("제육덮밥", 4, 40000), ("돈까스", 4, 40000)], r_total=80000),
    case("R08b_조금초과", "80,400원 ÷ 4명 = 20,100원", expect=["R08"], amount="80,400",
         r_items=[("제육덮밥", 4, 40400), ("돈까스", 4, 40000)], r_total=80400),
    # R09 식비·다과비 결제 시각
    case("R09a_식비60분", "18:30 종료, 19:30 결제 (경계, 통과)", r_datetime="2026-10-14 19:30:00"),
    case("R09b_식비61분", "18:30 종료, 19:31 결제", expect=["R09"], r_datetime="2026-10-14 19:31:00"),
    case("R09c_다과30분전", "다과비, 16:30 결제 → 17:00 시작 (경계, 통과)", r_merchant="가온베이커리", r_items=SNACK, r_total=34000,
         amount="34,000", r_datetime="2026-10-14 16:30:00"),
    case("R09d_다과31분전", "다과비, 16:29 결제 → 17:00 시작", expect=["R09"], r_merchant="가온베이커리", r_items=SNACK, r_total=34000,
         amount="34,000", r_datetime="2026-10-14 16:29:00"),
    case("R09e_다과회의후", "샌드위치 포함 품목을 회의 끝난 뒤 결제 → 식비면 통과·다과비면 위반으로 엇갈려 확인필요", review=["R09"],
         r_merchant="가온베이커리", r_items=SNACK, r_total=34000, amount="34,000", r_datetime="2026-10-14 18:40:00"),
    case("R09g_다과만회의후", "아메리카노·쿠키만(분명한 다과비)을 회의 끝난 뒤 결제", expect=["R09"], r_merchant="가온베이커리",
         r_items=[("아메리카노", 4, 12000), ("쿠키", 4, 10000)], r_total=22000, amount="22,000", r_datetime="2026-10-14 18:40:00"),
    case("R09f_식비회의전", "식비인데 회의 시작 전 결제", expect=["R09"], r_datetime="2026-10-14 16:40:00"),
    # R10 회의 시간
    case("R10a_59분", "17:00~17:59 회의", expect=["R10"], end="17:59", r_datetime="2026-10-14 18:20:00"),
    case("R10b_60분", "17:00~18:00 회의 (경계, 통과)", end="18:00", r_datetime="2026-10-14 18:20:00"),
    # R11 지역
    case("R11a_광산구", "광주광역시 광산구 가맹점", expect=["R11"], r_address="광주광역시 광산구 하남대로 0"),
    case("R11b_줄임표기", "'광주 북구'로 줄여 쓴 주소 (북구, 통과)", r_address="광주 북구 용봉로 0"),
    case("R11c_담양", "광주 밖(담양) → 지침상 북구만 가능하므로 미충족", expect=["R11"], r_address="전라남도 담양군 담양읍 0"),
    # R12 장소
    case("R12a_스타벅스", "회의 장소가 스타벅스 (카페 글자 없음)", expect=["R12"], place="스타벅스 전남대후문점"),
    case("R12b_스터디카페", "회의 장소가 스터디카페", expect=["R12"], place="용봉동 스터디카페 3층"),
    case("R12c_도서관", "중앙도서관 그룹스터디룸 (통과)", place="중앙도서관 3층 그룹스터디룸 2"),
    case("R12d_학생회실", "자연과학대학 1호관 학생회실 (실제 제출본, 통과)", place="자연과학대학 1호관 학생회실"),
    # R13 회의내용
    case("R13a_한줄", "회의내용 '회의함'", expect=["R13"], content=["회의함"]),
    case("R13b_형식적", "회의내용 두 줄, 결과 없음", expect=["R13"], content=["진행 상황 공유", "다음 회의 일정 논의"]),
    # R14 참석자 서명
    case("R14a_1명없음", "참석자 1명 서명 칸 비어 있음", expect=["R14"], attendees=A[:2] + [(*A[2][:3], False)] + A[3:]),
    case("R14b_워드서명", "참석자 1명 서명을 타자로", expect=["R14"], attendees=A[:3] + [(*A[3][:3], "typed")]),
    case("R14c_전원없음", "참석자 전원 서명 없음", expect=["R14"], attendees=[(*a[:3], False) for a in A]),
    # R15 사용 비용
    case("R15a_불일치", "사용 비용 65,000원 ≠ 영수증 60,000원", expect=["R15"], amount="65,000"),
    case("R15b_쉼표없음", "사용 비용 '60000' (통과)", amount="60000"),
    # R16 결제자
    case("R16a_서명없음", "결제자 서명 칸 비어 있음", expect=["R16"], payer=("인공지능학부", "김가온", False)),
    case("R16b_이름없음", "결제자 소속·이름 빈칸", expect=["R16"], payer=("", "", True)),
    # R17 제출 기한
    case("R17a_7일째1759", "10/14 사용 → 10/21 17:59 접수 (통과)", submitted_at="2026-10-21 17:59"),
    case("R17b_7일째1800", "10/14 사용 → 10/21 18:00 접수", expect=["R17"], submitted_at="2026-10-21 18:00"),
    # 회의일시 표기 (모두 통과해야 함)
    case("D1_띄어쓰기", "회의일시 '2026. 10. 14.(수) 17:00 ~ 18:30'", when_text="2026. 10. 14.(수) 17:00 ~ 18:30"),
    case("D2_오후표기", "회의일시 '10월 14일(수) 오후 5시~6시 30분'", when_text="10월 14일(수) 오후 5시~6시 30분"),
    case("D3_하이픈", "회의일시 '2026-10-14 17:00-18:30'", when_text="2026-10-14 17:00-18:30"),
    # F00 양식 미기재
    case("F1_회의명예시", "회의명 칸에 예시 글 '회의 주제' 그대로 → 부적합", expect=["F00"], title="회의 주제"),
    case("F2_내용예시", "회의내용 칸에 예시 글 그대로 → 부적합", expect=["F00", "R13"], content=["활동내용 자세하게 작성"]),
    # 복합
    case("M1_토요일밤맥주", "토요일 19:00~20:30 회의, 21:10 호프 결제(맥주)", expect=["R05", "R06", "R07"], date=d(10, 17), start="19:00",
         end="20:30", r_merchant="용봉호프", r_items=[("치킨", 2, 36000), ("생맥주", 4, 24000)], r_datetime="2026-10-17 21:10:00",
         submitted_at="2026-10-19 10:00"),
]
