"""조건 판정 R01~R17 (experiments/aicollege_upstage/run_cases.py `judge` 이식).

계산은 코드, 의미 판단(R07 주류, R09 식비/다과비 구분, R12 장소, R13 내용)은 Solar 결과를 받아 쓴다.
기준값은 DB `rule_sets.conditions[].params`에서 읽는다. 조건은 `type`으로 판정 함수를 고른다.

결과 값: met(충족) / unmet(미충족) / review(확인필요) / excluded(제외)
애매하면 review. 학생 회신에는 unmet만 들어가고 review는 담당자 메모로만 간다.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

MET, UNMET, REVIEW, EXCLUDED = "met", "unmet", "review", "excluded"
_SOLAR = {"ok": MET, "violation": UNMET}


def hm(s):
    m = re.search(r"(\d{1,2}):(\d{2})", s or "")
    return (int(m[1]), int(m[2])) if m else None


def _date(s) -> date | None:
    return date.fromisoformat(s[:10]) if re.match(r"\d{4}-\d{2}-\d{2}", s or "") else None


def _at(d: date, t) -> datetime:
    return datetime.combine(d, datetime.min.time()).replace(hour=t[0], minute=t[1])


def paid_amount(ie: dict) -> tuple[float, float | None]:
    """→ (판정에 쓸 실제 결제금액, 다르게 읽을 수 있는 금액|None). 할인 계산은 코드가 한다.
    추출이 할인 전·후를 뒤바꿔 줄 수 있어서, 단정할 수 없으면 두 번째 값을 함께 돌려준다 (금액 일치 조건이 확인필요로 보낸다)."""
    total, paid = ie.get("receipt_total") or 0, ie.get("receipt_paid") or 0
    discount = abs(ie.get("receipt_discount") or 0)
    if not discount < total:  # 합계 이상인 할인은 잘못 읽은 값
        discount = 0
    if discount:
        if paid:
            return paid, total - discount if paid == total else None
        return total - discount, total
    if not total:
        return paid, None
    # 할인을 못 읽었을 때 추출의 결제금액은 지어내거나(합계와 다른 값) 양식의 사용 비용을 베낄 때가 있다(2026-11-02 회귀 A06·A14).
    # 합계보다 작고 사용 비용 칸과 같을 때만 할인 뒤 금액으로 본다. 합계보다 큰 결제금액은 있을 수 없어 버린다.
    if paid and paid < total:
        ua = int(re.sub(r"\D", "", str(ie.get("used_amount") or "")) or 0)
        return (paid, total) if ua == paid else (total, paid)
    return total, None


class Ctx:
    """판정 한 번에 쓰는 값 모음."""

    def __init__(self, ie: dict, sj: dict, marks: dict, submitted_at: datetime | None):
        self.ie, self.sj, self.marks, self.submitted_at = ie, sj, marks, submitted_at
        self.total, self.total_alt = paid_amount(ie)
        self.tx = ie.get("transaction_datetime") or ""
        self.txd = _date(self.tx)
        self.paid = hm(self.tx[11:]) if len(self.tx) > 11 else None
        self.md = _date(ie.get("meeting_date"))
        self.start, self.end = hm(ie.get("start_time")), hm(ie.get("end_time"))
        self.n = len(ie.get("attendees") or [])


# 각 함수는 (result, message, field, found, expected)를 돌려준다.

NO_RECEIPT = "영수증 미첨부"  # 영수증 칸이 비어 있고 영수증 값도 없음 → 영수증에 기대는 조건은 화면에 띄우지 않는다


def receipt_attached(c: Ctx, p: dict):
    # 추출의 예/아니오(receipt_attached) 하나에 맡기지 않는다: 영수증 칸 그림(코드) + 영수증 값이 실제로 뽑혔는지로 본다.
    values = c.total > 0 and bool(c.ie.get("merchant_name") or c.tx)
    img = c.marks.get("receipt_image")
    flag = "" if bool(c.ie.get("receipt_attached")) == bool(values) else f" (추출의 첨부 여부 값은 {c.ie.get('receipt_attached')})"
    if values and img is not False:
        return MET, f"영수증 첨부, 합계 {c.total:,}원" + flag, "receipt_total", f"{c.total:,}원", "영수증 첨부, 금액 > 0"
    if img and not values:  # 사진은 붙었는데 글자를 못 읽음 → 추측하지 않고 다시 제출 요청 (사람도 읽기 어려우면 검수 불가, 2026-10-31 종희 결정)
        return (UNMET, "영수증 사진이 흐리거나 잘려 내용을 읽을 수 없습니다. 가맹점·거래일시·승인번호·합계가 보이는 선명한 영수증 사진으로 다시 제출해 주세요."
                + flag, "receipt", "사진 있음, 글자 판독 불가", "영수증 내용 판독 가능")
    if values:
        return REVIEW, "영수증 칸에서 그림을 찾지 못했지만 영수증 값은 읽혔습니다. 원본 확인 필요" + flag, "receipt", "그림 없음, 값 있음", "영수증 첨부"
    return UNMET, "영수증 미첨부: 영수증이 첨부되지 않았습니다. 연구비카드 영수증 사진을 붙여 다시 제출해 주세요.", "receipt", NO_RECEIPT, "영수증 첨부"


def card_slip(c: Ctx, p: dict):
    """연구비카드로 결제한 카드 영수증인가. 실제 영수증은 가게 영수증에 카드 결제 정보(카드번호·카드명·매입사·승인번호)가 찍혀 오고
    '연구비카드' 글자는 없다(2026-10-31 성장통). 그래서 카드번호 앞자리(card_bins)나 카드명 단어(card_words)로 연구비카드를 알아본다."""
    rt, ct = c.ie.get("receipt_type") or "", c.ie.get("card_type") or ""
    no = re.sub(r"\D", "", c.ie.get("card_number") or "")
    found = f"{rt or '종류 없음'} / 카드 {ct or '없음'} / 번호 {c.ie.get('card_number') or '없음'}"
    exp = "연구비카드 결제 영수증 (간이·현금영수증 불가)"
    if any(w in rt for w in p.get("reject_words", [])):
        return UNMET, f"'{rt}'은(는) 인정되지 않는 영수증입니다. 연구비카드로 결제한 카드 영수증만 인정됩니다.", "receipt_type", found, exp
    words = p.get("card_words") or [p.get("card_word", "연구비카드")]
    # 카드사 매출전표는 '533014******0110'처럼 앞 6자리만 보인다 → 보이는 앞자리가 연구비카드 번호와 겹치면 인정 (2026-11-02 성장통 위밋)
    lead = re.sub(r"\D", "", re.match(r"[\d\s-]*", c.ie.get("card_number") or "")[0])
    bins = p.get("card_bins") or []
    is_research = (any(no.startswith(b) for b in bins) or any(len(lead) >= 6 and (b.startswith(lead) or lead.startswith(b)) for b in bins)
                   or any(w in ct for w in words))
    if is_research:
        return MET, f"연구비카드 결제 ({ct or ''} {c.ie.get('card_number') or ''})".strip(), "card_type", found, exp
    if not ct and len(no) >= 6:  # 번호는 있는데 카드명을 못 읽음 → 번호만으로 다른 카드라고 단정하지 않는다
        return REVIEW, f"카드명을 읽지 못해 연구비카드인지 확인이 필요합니다 (카드번호 {c.ie.get('card_number')})", "card_type", found, exp
    if ct:  # 카드명이 연구비카드 표기가 아님 (개인카드 등)
        return UNMET, f"연구비카드가 아닌 카드로 결제했습니다 ({ct or '카드'} {c.ie.get('card_number') or ''}). 연구비카드로 결제한 영수증만 인정됩니다.".replace("  ", " "), "card_type", found, exp
    return REVIEW, f"영수증에서 카드 결제 정보를 찾지 못했습니다 ({found})", "receipt_type", found, exp


def receipt_items(c: Ctx, p: dict):
    """영수증에 메뉴·품목이 적혀 있는가. 지침 '영수증 내역 필수'. 없으면 학생에게 지적하지 않고 담당자 확인 (2026-11-02 종희)."""
    items = [str(i.get("name") or "").strip() for i in c.ie.get("receipt_items") or []]
    items = [x for x in items if x]
    if items:
        return MET, f"품목 {len(items)}개: {', '.join(items[:4])}{' 등' if len(items) > 4 else ''}", "receipt_items", ", ".join(items[:6]), "영수증 품목 표기"
    return REVIEW, "영수증에 메뉴·품목 내역이 보이지 않습니다. 담당자 확인이 필요합니다 (카드사 매출전표만 붙인 경우 등).", "receipt_items", None, "영수증 품목 표기"


def approval_number(c: Ctx, p: dict):
    ap = c.ie.get("approval_number") or ""
    if len(re.sub(r"\D", "", ap)) >= 6:  # '7950 9130'처럼 띄어 쓴 승인번호도 인정 (2026-11-02 NoBrains)
        return MET, f"승인번호 {ap}", "approval_number", ap, "승인번호 표기"
    return UNMET, "영수증에 승인번호가 없습니다.", "approval_number", ap or None, "승인번호 표기"


def same_date(c: Ctx, p: dict):
    found = f"회의 {c.md or '?'} / 거래 {c.txd or '?'}"
    if not (c.md and c.txd):
        return REVIEW, f"회의일 또는 거래일을 읽지 못했습니다 ({found})", "meeting_date", found, "회의일 = 거래일"
    if c.md == c.txd:
        return MET, found, "meeting_date", found, "회의일 = 거래일"
    return UNMET, f"회의일({c.md:%m/%d})과 영수증 거래일({c.txd:%m/%d})이 다릅니다.", "transaction_datetime", found, "회의일 = 거래일"


def weekday_only(c: Ctx, p: dict):
    if not c.txd:
        return REVIEW, "거래일을 읽지 못했습니다.", "transaction_datetime", None, "평일"
    wd = "월화수목금토일"[c.txd.weekday()]
    if c.txd.weekday() < 5:
        return MET, f"거래일 {wd}요일", "transaction_datetime", f"{wd}요일", "평일"
    return UNMET, f"주말({c.txd:%m/%d} {wd}요일)에 사용했습니다. 주말 사용은 인정되지 않습니다.", "transaction_datetime", f"{wd}요일", "평일"


def pay_before(c: Ctx, p: dict):
    lim = hm(p["time"])
    found = c.tx[11:16] or None
    if not c.paid:
        return REVIEW, "결제 시각을 읽지 못했습니다.", "transaction_datetime", found, f"{p['time']} 이전"
    if c.paid < lim:
        return MET, f"결제 {found} / 기준 {p['time']} 이전", "transaction_datetime", found, f"{p['time']} 이전"
    return UNMET, f"{found}에 결제했습니다. {p['time']} 이전 결제만 인정됩니다.", "transaction_datetime", found, f"{p['time']} 이전"


# 글자로 분명한 위반은 Solar 답과 관계없이 코드가 잡는다 (A11에서 Solar가 이유엔 '위반'이라 쓰고 ok를 준 사례, 2026-10-31)
PLACE_WORDS = ["카페", "커피", "식당", "음식점", "레스토랑", "cafe", "coffee", "restaurant"]
# 학교 안 회의 공간 단어. 음식점 단어 없이 이 단어가 있으면 Solar 판단보다 코드가 우선한다
# (Solar가 '전남대학교 7호관 스터디라운지'를 카페로 본 사례, 2026-11-02 전자파)
CAMPUS_PLACE_WORDS = ["호관", "강의실", "회의실", "연구실", "실험실", "세미나실", "스터디룸", "스터디라운지", "학습실", "동아리방", "동아리실", "도서관"]
ALCOHOL_WORDS = ["주점", "호프", "포차", "술집", "맥주", "소주", "막걸리", "와인", "하이볼", "beer"]
# 가맹점 이름에 있으면 술집이 분명해 미충족. 품목에만 술 글자가 있으면 '와인무화과휘낭시에'처럼 술이 아닐 수 있어
# 어느 품목인지 적어 확인필요로 둔다 (2026-11-04 종희, AiBara)
BAR_WORDS = ["주점", "호프", "포차", "술집"]


def _keyword(c: Ctx, key: str) -> str | None:
    if key == "place":
        text, words = c.ie.get("place") or "", PLACE_WORDS
    elif key == "alcohol":
        items = " ".join(str(i.get("name") or "") for i in c.ie.get("receipt_items") or [])
        text, words = f"{c.ie.get('merchant_name') or ''} {items}", ALCOHOL_WORDS
    else:
        return None
    low = text.lower()
    return next((w for w in words if w in low), None)


def _alcohol_items(c: Ctx) -> list[str]:
    return [str(i.get("name")) for i in c.ie.get("receipt_items") or [] if any(w in str(i.get("name") or "").lower() for w in ALCOHOL_WORDS)]


def _solar(key: str, field: str, unmet_msg: str):
    def f(c: Ctx, p: dict):
        if key == "alcohol":
            merchant = (c.ie.get("merchant_name") or "").lower()
            if w := next((x for x in BAR_WORDS if x in merchant), None):
                return UNMET, f"{unmet_msg} ('{w}' 확인)", field, w, None
            if items := _alcohol_items(c):
                names = ", ".join(f"'{n}'" for n in items[:3])
                return REVIEW, f"품목 {names}에 술 이름 글자가 있습니다. 주류인지 확인해 주세요.", "receipt_items", names, None
            d, reason = c.sj[key]["decision"], c.sj[key]["reason"]
            if d == "violation":  # 글자로 분명하지 않은 Solar 위반 판단은 담당자 확인으로
                return REVIEW, f"주류·술집일 수 있습니다. 확인해 주세요 ({reason})", field, reason, None
            return _SOLAR.get(d, REVIEW), reason, field, reason, None
        if w := _keyword(c, key):
            return UNMET, f"{unmet_msg} ('{w}' 확인)", field, w, None
        if key == "place" and (w := next((x for x in CAMPUS_PLACE_WORDS if x in (c.ie.get("place") or "").replace(" ", "")), None)):
            return MET, f"학교 안 회의 공간 ('{w}')", field, c.ie.get("place"), None
        d, reason = c.sj[key]["decision"], c.sj[key]["reason"]
        r = _SOLAR.get(d, REVIEW)
        msg = f"{unmet_msg} ({reason})" if r == UNMET else reason
        return r, msg, field, reason, None
    return f


no_alcohol = _solar("alcohol", "merchant_name", "술집 결제 또는 주류 구매는 인정되지 않습니다.")
place_not_food = _solar("place", "place", "회의 장소가 카페·식당입니다. 연구실·회의실·실험실 등에서 회의해야 합니다.")
content_specific = _solar("content", "content", "회의내용을 구체적으로(논의 내용과 결과) 적어 주세요.")


def per_person_limit(c: Ctx, p: dict):
    limit = p["limit"]
    if not c.n:
        return REVIEW, "참석자 수를 읽지 못했습니다.", "attendees", None, f"≤ {limit:,}원"
    per = c.total / c.n
    found = f"{c.total:,} ÷ {c.n}명 = {per:,.0f}원"
    if per <= limit:
        return MET, f"{found} / 한도 {limit:,}원", "receipt_total", found, f"≤ {limit:,}원"
    return UNMET, f"1인당 {per:,.0f}원({found})으로 한도 {limit:,}원을 넘습니다.", "receipt_total", found, f"≤ {limit:,}원"


# 식비·다과비 품목 단어. 품목이 한쪽 단어로만 되어 있으면 코드가 정한다(Solar가 아메리카노·쿠키·샌드위치를 식비로 본 사례, 2026-10-31)
SNACK_WORDS = ["커피", "아메리카노", "라떼", "카페", "음료", "주스", "에이드", "스무디", "티", "차", "쿠키", "빵", "케이크", "케익", "과자",
               "도넛", "머핀", "베이글", "샌드위치", "마카롱", "와플", "스콘", "크로와상", "아이스크림", "콜라", "사이다", "생수", "물"]
MEAL_WORDS = ["밥", "덮밥", "백반", "정식", "찌개", "국", "탕", "면", "라면", "국수", "냉면", "짜장", "짬뽕", "김밥", "떡볶이", "고기",
              "삼겹살", "갈비", "치킨", "피자", "버거", "햄버거", "돈까스", "돈가스", "볶음", "도시락", "족발", "보쌈", "만두", "초밥", "카레"]


def expense_kind(c: Ctx) -> tuple[str, str]:
    """→ (식비|다과비|불명, 근거). 품목 단어로 분명하면 코드, 섞이거나 모르면 Solar. 둘이 어긋나면 불명."""
    items = [str(i.get("name") or "") for i in c.ie.get("receipt_items") or []]
    snack = [n for n in items if any(w in n for w in SNACK_WORDS) and not any(w in n for w in MEAL_WORDS)]
    meal = [n for n in items if any(w in n for w in MEAL_WORDS)]
    code = "다과비" if items and len(snack) == len(items) else "식비" if meal else None
    solar = c.sj["expense_kind"]["kind"]
    if code and solar in (code, "불명"):
        return code, f"품목({', '.join(items)})으로 {code}"
    if code and solar != code:
        return "불명", f"품목 단어로는 {code}, AI는 {solar}로 봐서 엇갈림"
    return solar, c.sj["expense_kind"]["reason"]


def _window(kind: str, start, end, paid, p: dict):
    if kind == "식비":
        gap = (paid - end).total_seconds() / 60
        found = f"식비: 종료 {end:%m-%d %H:%M} → 결제 {paid:%m-%d %H:%M} ({gap:.0f}분 후)"
        exp = f"회의 후 {p['meal_after']}분 이내"
        if 0 <= gap <= p["meal_after"]:
            return MET, found + f", 기준 {p['meal_after']}분", found, exp
        return UNMET, f"식비는 회의 종료 후 {p['meal_after']}분 이내에 결제해야 합니다 ({found}).", found, exp
    gap = (start - paid).total_seconds() / 60
    found = f"다과비: 결제 {paid:%m-%d %H:%M} → 시작 {start:%H:%M} ({gap:.0f}분 전)"
    exp = f"회의 전 {p['snack_before']}분 이내"
    if 0 <= gap <= p["snack_before"]:
        return MET, found + f", 기준 {p['snack_before']}분", found, exp
    return UNMET, f"다과비는 회의 시작 전 {p['snack_before']}분 이내에 결제해야 합니다 ({found}).", found, exp


def pay_window(c: Ctx, p: dict):
    kind, why = expense_kind(c)
    if not (c.start and c.end and c.paid and c.md and c.txd):
        return REVIEW, "회의 시각 또는 결제 일시를 읽지 못했습니다.", "transaction_datetime", None, None
    start, end, paid = _at(c.md, c.start), _at(c.md, c.end), _at(c.txd, c.paid)
    if kind in ("식비", "다과비"):
        r, msg, found, exp = _window(kind, start, end, paid, p)
        return r, msg, "transaction_datetime", found, exp
    # 식비·다과비가 애매하면 두 가지로 모두 계산: 둘 다 위반이면 미충족, 둘 다 통과면 충족, 엇갈릴 때만 확인필요
    meal, snack = _window("식비", start, end, paid, p), _window("다과비", start, end, paid, p)
    found = f"{meal[2]} / {snack[2]}"
    alts = [{"label": "식비로 보면", "result": meal[0], "detail": meal[2], "expected": meal[3]},
            {"label": "다과비로 보면", "result": snack[0], "detail": snack[2], "expected": snack[3]}]
    exp = f"식비 회의 후 {p['meal_after']}분 이내 · 다과비 회의 전 {p['snack_before']}분 이내"
    if meal[0] == snack[0] == UNMET:
        return UNMET, "식비로 보든 다과비로 보든 결제 시각이 기준 밖입니다.", "transaction_datetime", found, exp, alts
    if meal[0] == snack[0] == MET:
        return MET, "식비·다과비 어느 쪽으로 봐도 결제 시각이 기준 안입니다.", "transaction_datetime", found, exp, alts
    ok, ng = ("식비", "다과비") if meal[0] == MET else ("다과비", "식비")
    return (REVIEW, f"{ok}로 보면 통과, {ng}로 보면 위반이라 담당자 확인이 필요합니다 (구분이 애매한 이유: {why}).",
            "receipt_items", found, exp, alts)


def min_meeting(c: Ctx, p: dict):
    mins = p["minutes"]
    if not (c.start and c.end):
        return REVIEW, "회의 시각을 읽지 못했습니다.", "start_time", None, f"≥ {mins}분"
    dur = (c.end[0] * 60 + c.end[1]) - (c.start[0] * 60 + c.start[1])
    found = f"{c.ie.get('start_time')}~{c.ie.get('end_time')} ({dur}분)"
    if dur >= mins:
        return MET, f"{found} / 기준 {mins}분", "start_time", found, f"≥ {mins}분"
    return UNMET, f"회의 시간이 {dur}분입니다. {mins}분 이상 운영해야 합니다.", "start_time", found, f"≥ {mins}분"


def _city(name: str) -> str:
    # 통합 시 이름도 광주로 본다: 카드 전표에 '전남광주통합특별시 북구 …'로 찍혀 온다 (2026-11-03 EPOCH).
    # 북구가 아니면(나주시 등) 아래에서 금지 구도 다른 시·도도 아니라 확인필요로 남는다.
    if re.fullmatch(r"(전남광주|광주전남)통합특별시", name):
        return "광주"
    return re.sub(r"(광역시|특별시|특별자치시|시)$", "", name)


def region(c: Ctx, p: dict):
    """시(광주)와 구(북구)를 따로 본다. '광주 북구' 같은 줄임 표기를 받고, '서울 강남구'를 '남구'로 오인하지 않는다."""
    raw = c.ie.get("merchant_address") or ""
    tokens = raw.replace(",", " ").split()
    exp = f"{p['allowed']} 가맹점"
    if not tokens:
        return REVIEW, "가맹점 주소를 읽지 못했습니다.", "merchant_address", None, exp
    city, gu = _city(p["allowed"].split()[0]), p["allowed"].split()[-1]
    in_city = any(_city(t).startswith(city) for t in tokens[:2])
    if in_city and gu in tokens:
        return MET, raw, "merchant_address", raw, exp
    if not in_city and tokens[0] == gu:  # 시 이름 없이 '북구'만 읽힘 → 다른 시의 북구일 수 있어 영수증을 다시 본다 (2026-11-04 종희)
        return REVIEW, f"가맹점 주소({raw})에 시 이름 없이 '{gu}'만 읽혔습니다. 영수증에서 {p['allowed']}인지 확인해 주세요.", "merchant_address", raw, exp
    if in_city and any(x in tokens for x in p.get("prohibited") or []):
        return UNMET, f"가맹점({raw})이 사용 가능 지역({p['allowed']}) 밖입니다.", "merchant_address", raw, exp
    if not in_city and re.match(r"(서울|부산|대구|인천|대전|울산|세종|경기|강원|충청|충북|충남|전라|전북|전남|경상|경북|경남|제주)", tokens[0]):
        return UNMET, f"가맹점({raw})이 사용 가능 지역({p['allowed']}) 밖입니다.", "merchant_address", raw, exp
    return REVIEW, f"{raw} — {p['allowed']}인지 단정할 수 없습니다.", "merchant_address", raw, exp


def attendee_signatures(c: Ctx, p: dict):
    # 칸 확인(그림/글자)이 우선, 추출값은 참고. "typed" = 워드 작성 서명 (양식상 불가)
    ie_sig = {a.get("name"): bool(a.get("has_signature")) for a in c.ie.get("attendees") or []}
    loc = c.marks.get("attendee_signed") or {}
    exp = "참석자 전원 서명 (워드 작성 불가)"
    if loc:
        missing = [k for k, v in loc.items() if v is False]
        typed = [k for k, v in loc.items() if v == "typed"]
        note = [k for k in loc if k in ie_sig and ie_sig[k] != (loc[k] is True)]
        extra = f" (추출값과 다름: {', '.join(note)})" if note else ""
        if missing or typed:
            parts = ([f"{', '.join(missing)} 님의 서명이 없습니다."] if missing else []) + \
                    ([f"{', '.join(typed)} 님의 서명이 워드로 작성되었습니다(자필·전자서명만 인정)."] if typed else [])
            found = "; ".join(([f"서명 없음: {', '.join(missing)}"] if missing else []) + ([f"워드 작성: {', '.join(typed)}"] if typed else []))
            return UNMET, " ".join(parts) + extra, "attendees[].has_signature", found, exp
        return MET, f"{len(loc)}명 전원 서명" + extra, "attendees[].has_signature", f"{len(loc)}명 서명", exp
    missing = [k for k, v in ie_sig.items() if not v]
    if missing:
        return REVIEW, f"추출상 서명 없음: {', '.join(missing)} — 서명 칸 확인 필요", "attendees[].has_signature", None, exp
    return MET, "추출상 전원 서명", "attendees[].has_signature", None, exp


def amount_matches(c: Ctx, p: dict):
    ua = c.ie.get("used_amount") or 0
    gross, discount = c.ie.get("receipt_total") or 0, abs(c.ie.get("receipt_discount") or 0)
    basis = f" (합계 {gross:,} − 할인 {discount:,})" if discount and gross - discount == c.total else ""
    found = f"사용 비용 {ua:,} / 영수증 {c.total:,}" + basis
    exp = "사용 비용 = 영수증 결제금액(할인 반영)"
    if ua == c.total and c.total:
        return MET, found, "used_amount", found, exp
    if ua and ua == c.total_alt:  # 할인 전 금액인지 뒤 금액인지 단정할 수 없음 → 학생에게 지적하지 않는다
        return REVIEW, f"사용 비용 칸({ua:,}원)이 영수증 금액과 맞는지 할인 반영 여부를 확인해야 합니다 ({found}).", "used_amount", found, exp
    return UNMET, f"사용 비용 칸({ua:,}원)과 영수증 결제금액({c.total:,}원{basis})이 다릅니다.", "used_amount", found, exp


def payer_signature(c: Ctx, p: dict):
    ie, ps = c.ie, c.marks.get("payer_signed")
    exp = "결제자 소속·이름·서명"
    if not (ie.get("payer_name") and ie.get("payer_affiliation")):
        return UNMET, "결제자 소속·이름이 없습니다.", "payer_name", None, exp
    who = f"{ie.get('payer_affiliation')} {ie.get('payer_name')}"
    if ps is True or (ps is None and ie.get("payer_has_signature")):
        return MET, f"{who} 서명 있음" + (" (추출값은 없음)" if not ie.get("payer_has_signature") else ""), "payer_has_signature", who, exp
    if ps is False:
        return UNMET, "결제자 서명이 없습니다.", "payer_has_signature", "서명 칸 비어 있음", exp
    if ps == "typed":
        return UNMET, "결제자 서명이 워드로 작성되었습니다(자필·전자서명만 인정).", "payer_has_signature", "워드 작성", exp
    return REVIEW, "결제자 서명 확인 필요", "payer_has_signature", None, exp


def submit_within_days(c: Ctx, p: dict):
    t = hm(p.get("deadline_time", "18:00"))
    if not (c.txd and c.submitted_at):
        return REVIEW, "거래일 또는 접수 일시가 없습니다.", "transaction_datetime", None, None
    dl = _at(c.txd + timedelta(days=p["days"]), t)
    found = f"접수 {c.submitted_at:%m-%d %H:%M} / 기한 {dl:%m-%d %H:%M}"
    exp = f"사용일로부터 {p['days']}일째 {p.get('deadline_time', '18:00')} 전"
    if c.submitted_at < dl:
        return MET, found, "received_at", found, exp
    return UNMET, f"제출 기한({dl:%m/%d %H:%M})이 지났습니다 (접수 {c.submitted_at:%m/%d %H:%M}).", "received_at", found, exp


JUDGES = {
    "receipt_attached": receipt_attached, "card_slip": card_slip, "approval_number": approval_number, "same_date": same_date,
    "weekday_only": weekday_only, "pay_before": pay_before, "no_alcohol": no_alcohol, "per_person_limit": per_person_limit,
    "pay_window": pay_window, "min_meeting": min_meeting, "region": region, "place_not_food": place_not_food,
    "content_specific": content_specific, "attendee_signatures": attendee_signatures, "amount_matches": amount_matches,
    "payer_signature": payer_signature, "submit_within_days": submit_within_days, "receipt_items": receipt_items,
}


def source_text(src) -> str | None:
    if not src:
        return None
    vals = []
    for v in src.values() if isinstance(src, dict) else [src]:
        vals += v if isinstance(v, list) else [v]
    return " / ".join(str(v) for v in vals if v)[:300] or None


def judge(ie: dict, sj: dict, marks: dict, submitted_at: datetime | None, conditions: list[dict], removed: list[dict] = ()) -> list[dict]:
    """조건 목록대로 판정한다. 반환은 API `checks[]` 모양 (file_id·page는 호출하는 쪽에서 채운다)."""
    c = Ctx(ie, sj, marks, submitted_at)
    out = []
    for cond in conditions:
        if not cond.get("enabled", True):
            continue
        fn = JUDGES.get(cond["type"])
        if fn is None:  # 코드가 모르는 조건 유형 → 담당자 확인
            r = (REVIEW, "자동 판정할 수 없는 조건입니다. 담당자 확인 필요", None, None, None)
        else:
            r = fn(c, cond.get("params") or {})
        result, message, field, found, expected, alternatives = (*r, None, None, None, None)[:6]
        out.append({"check_id": cond["id"], "name": cond["name"], "by": cond["by"], "severity": cond["severity"],
                    "result": result, "ai_result": result, "overridden": False, "message": message,
                    "evidence": {"field": field, "found": found, "expected": expected, "file_id": None, "page": None, "bbox": None,
                                 "rule_source": source_text(cond.get("source")), "alternatives": alternatives},
                    "manager_note": None})
    # 영수증을 못 읽었으면(R01 미충족·확인필요) 영수증 값에 기대는 조건은 미충족으로 두지 않는다.
    # 합계 0원 → '사용 비용 불일치', 승인번호 없음 같은 덧붙은 지적이 학생에게 가지 않게 (2026-10-31 실험 R01a·R01b)
    r01 = next((o for o in out if o["check_id"] == "R01"), None)
    if r01 and r01["result"] != MET:
        dependent = {"card_slip", "approval_number", "same_date", "weekday_only", "pay_before", "no_alcohol", "per_person_limit",
                     "pay_window", "region", "amount_matches", "submit_within_days", "receipt_items"}
        types = {cond["id"]: cond["type"] for cond in conditions}
        if r01["evidence"]["found"] == NO_RECEIPT:  # 영수증 자체가 없으면 영수증 조건은 빼고 '영수증 미첨부' 하나만 보인다 (2026-11-02 종희)
            out = [o for o in out if types.get(o["check_id"]) not in dependent]
            used = "" if ie.get("used_amount") in (None, "") else re.sub(r"\D", "", str(ie["used_amount"]))  # 0원은 빈 칸과 다르게 본다
            if used and not used.strip("0"):  # 사용 비용 0원도 보완필요: 회의비 증빙은 카드 지출이 있어야 함 (2026-11-03 종희, VCCC 10.27)
                r01["message"] = ("영수증 미첨부: 사용 비용이 0원이고 영수증이 없습니다. 회의비 지출 증빙은 연구비카드로 결제한 영수증이 있어야 합니다. "
                                  "지출한 영수증 사진과 사용 비용을 채워 다시 제출해 주세요.")
            elif not used:  # 영수증 미첨부는 모두 보완필요 (2026-11-02 종희)
                r01["message"] = "영수증 미첨부: 영수증과 사용 비용이 모두 비어 있습니다. 연구비카드 영수증 사진과 사용 비용을 채워 다시 제출해 주세요."
        for o in out:
            if types.get(o["check_id"]) in dependent and o["result"] != MET:
                o["result"] = o["ai_result"] = REVIEW
                o["message"] = f"영수증을 읽지 못해 판정 보류 ({o['message']})"
    for rm in removed:
        out.append({"check_id": rm["id"], "name": rm["name"], "by": "code", "severity": "needs_fix", "result": EXCLUDED, "ai_result": EXCLUDED,
                    "overridden": False, "message": rm.get("excluded_reason") or "이번 기준에서 제외된 조건",
                    "evidence": {"field": None, "found": None, "expected": None, "file_id": None, "page": None, "bbox": None, "rule_source": None},
                    "manager_note": None})
    return out
