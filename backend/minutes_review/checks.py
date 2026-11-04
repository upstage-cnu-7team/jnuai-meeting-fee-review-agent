"""판정: C1~C16 + 최종 판정. 계산은 코드가, 의미 판단(C8·C9·C11 사진)만 judge가 한다.

항목 결과: 충족 / 미충족 / 확인필요 / 참고(C2, 판정 제외).
최종 판정: 등급 '부적합' 항목이 미충족 → 부적합, 그 외 미충족 → 보완필요, 확인필요만 → 확인필요, 모두 충족 → 적합.
등급(부적합·보완필요)과 기준값은 rules/*.yaml에서 온다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .fields import Field, Fields, _method
from .judge import OK, VIOLATION, Judge, Question
from .rules import Rules

MET, UNMET, CHECK, INFO = "충족", "미충족", "확인필요", "참고"


@dataclass
class Check:
    id: str
    name: str
    result: str
    severity: str
    basis: str  # 기준
    detail: str  # 판정 설명
    action: str  # 학생에게 요청할 조치
    evidence: list[dict] = field(default_factory=list)
    by: str = "코드"

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "result": self.result, "severity": self.severity, "basis": self.basis,
                "detail": self.detail, "action": self.action, "evidence": self.evidence, "by": self.by}


def won(n) -> str:
    return f"{n:,.0f}원" if isinstance(n, (int, float)) else "(없음)"


def _v(f: Field, fmt=str) -> str:
    return fmt(f.value) if f.value not in (None, "", []) else "(빈 값)"


def run_checks(f: Fields, rules: Rules, judge: Judge) -> tuple[list[Check], str]:
    checks: list[Check] = []
    sev = rules.severity
    R = f.receipt
    ocr = R.needs_ocr
    no_receipt = not R.present

    def add(cid, name, result, basis, detail, action, evidence, by="코드"):
        checks.append(Check(cid, name, result, sev.get(cid, "보완필요"), basis, detail,
                            action if result != MET else "", [e for e in evidence if e], by))

    def receipt_gap(cid, name, basis, ev_extra=()):
        """영수증 값이 없을 때: 사진 영수증이면 OCR 필요, 아예 없으면 C4에서 지적하므로 확인필요."""
        why = "영수증이 이미지(스캔·사진)라 글자를 읽지 못함 — OCR 필요" if ocr else "영수증에서 해당 값을 찾지 못함"
        add(cid, name, CHECK, basis, why, "영수증 원본으로 담당자가 직접 확인", list(ev_extra), "코드")

    # ── 의미 판단 질문 (한 번에 묶어 보냄)
    qs = []
    if f.place.value:
        qs.append(Question("C8", "place", f.place.value, "회의 장소는 음식점·카페가 아니어야 한다 (강의실·동아리실·회의실 등)"))
    content = f.content.value or ""
    guide_left = [p for p in rules.guide_phrases if p.replace(" ", "") in content.replace(" ", "")]
    if content and not guide_left:
        qs.append(Question("C9", "content", f"주제: {f.topic.value or ''} / 내용: {content}",
                           "회의 주제와 회의내용·결과가 구체적으로 기술되어야 한다 (형식적인 한두 줄 불가)"))
    if f.photos:
        qs.append(Question("C11", "photo", f"회의록 참석자 {len(f.attendees)}명, 사진 {len(f.photos)}장",
                           "사진에 회의비 사용 인원 전원이 나와야 하고, 음식점·카페에서 찍은 사진은 불가", list(f.photos)))
    answers, engine = judge.judge(qs) if qs else ({}, "의미 판단 항목 없음")

    # C1 동아리 구분 체크
    t1, t2 = f.club_type.value or [], f.attach_club_type.value or []
    ev = [f.club_type.ev(), f.attach_club_type.ev()]
    if f.minutes_page is None and f.attach_page is None:
        add("C1", "동아리 구분 체크", CHECK, "증빙서·첨부철의 동아리 구분에 체크", "양식 표를 찾지 못함", "양식에 맞춰 제출", ev)
    elif t1 and t2:
        res = MET if set(t1) == set(t2) else CHECK
        add("C1", "동아리 구분 체크", res, "증빙서·첨부철의 동아리 구분에 체크",
            f"증빙서 {', '.join(t1)} / 첨부철 {', '.join(t2)}" + ("" if res == MET else " — 두 서류의 체크가 다름"),
            "두 서류의 동아리 구분을 같게 체크", ev)
    else:
        miss = [n for n, t in (("회의비 지출 증빙", t1), ("영수증 첨부철", t2)) if not t]
        add("C1", "동아리 구분 체크", UNMET, "증빙서·첨부철의 동아리 구분에 체크", f"체크 없음: {', '.join(miss)}",
            f"{', '.join(miss)}의 '동아리 구분' 칸에 해당 구분을 체크(■)해 주세요", ev)

    # C2 동아리 분야 (참고)
    add("C2", "동아리 분야", INFO, "전공동아리만 작성 — 판정 제외", _v(f.club_field, lambda x: ", ".join(x)), "", [f.club_field.ev()])

    # C3 동아리명 일치
    n1, n2 = f.club_name.value, f.attach_club_name.value
    ev = [f.club_name.ev(), f.attach_club_name.ev()]
    if n1 and n2 and n1.replace(" ", "") == n2.replace(" ", ""):
        add("C3", "동아리명 일치", MET, "증빙서 동아리명 = 첨부철 동아리명", f"{n1}", "", ev)
    else:
        add("C3", "동아리명 일치", UNMET, "증빙서 동아리명 = 첨부철 동아리명",
            f"증빙서 '{n1 or '(빈 값)'}' / 첨부철 '{n2 or '(빈 값)'}'",
            "두 서류의 동아리명을 같게 기재해 주세요" if n1 and n2 else "비어 있는 동아리명 칸을 채워 주세요", ev)

    # C4 영수증 첨부, 금액 > 0
    if R.present and R.total.value:
        add("C4", "영수증 첨부", MET, "영수증 첨부, 결제금액 > 0", f"결제금액 {won(R.total.value)}", "", [R.total.ev()])
    elif ocr:
        add("C4", "영수증 첨부", CHECK, "영수증 첨부, 결제금액 > 0", "영수증이 이미지로 첨부됨 — 금액은 OCR 필요",
            "영수증 이미지를 담당자가 직접 확인", [{"page": R.page, "where": f"{R.page}쪽 영수증 이미지", "value": None}])
    else:
        add("C4", "영수증 첨부", UNMET, "영수증 첨부, 결제금액 > 0",
            "영수증이 없음" if no_receipt else "영수증에서 결제금액을 찾지 못함", "카드 영수증 원본을 첨부철에 붙여 제출해 주세요",
            [R.total.ev()] if R.present else [])

    meet_date, rec_date = f.meeting_date.value, R.date.value

    # C5 회의일 = 영수증 거래일
    if meet_date is None:
        add("C5", "회의일·영수증 날짜 일치", CHECK, "회의일 = 영수증 거래일", "회의록에서 회의 날짜를 읽지 못함",
            "'일시 및 장소' 칸에 회의 날짜를 YYYY.MM.DD. 형식으로 기재", [f.meeting_date.ev()])
    elif rec_date is None:
        receipt_gap("C5", "회의일·영수증 날짜 일치", "회의일 = 영수증 거래일", [f.meeting_date.ev()])
    else:
        ok = meet_date == rec_date
        add("C5", "회의일·영수증 날짜 일치", MET if ok else UNMET, "회의일 = 영수증 거래일",
            f"회의일 {meet_date} / 영수증 거래일 {rec_date}",
            "회의비는 회의 당일 결제분만 인정됩니다. 회의일과 결제일이 다른 영수증은 회의비로 인정되지 않습니다",
            [f.meeting_date.ev(), R.date.ev()])

    # C6 첨부철 기재 날짜·금액 = 실제 영수증
    ad, aa = f.attach_date.value, f.attach_amount.value
    ev = [f.attach_date.ev(), f.attach_amount.ev(), R.date.ev(), R.total.ev()]
    if f.attach_page is None:
        add("C6", "첨부철 날짜·금액 기재", UNMET, "첨부철 기재 날짜·금액 = 영수증", "영수증 첨부철이 없음",
            "영수증 첨부철 양식에 날짜·금액을 적어 함께 제출해 주세요", [])
    elif ad is None or aa is None:
        miss = [n for n, v in (("날짜", ad), ("금액", aa)) if v is None]
        add("C6", "첨부철 날짜·금액 기재", UNMET, "첨부철 기재 날짜·금액 = 영수증", f"첨부철 {', '.join(miss)} 미기재",
            f"영수증 첨부철의 {', '.join(miss)} 칸을 영수증과 같게 적어 주세요", ev)
    elif rec_date is None or not R.total.value:
        receipt_gap("C6", "첨부철 날짜·금액 기재", "첨부철 기재 날짜·금액 = 영수증", ev[:2])
    else:
        diffs = []
        if ad != rec_date:
            diffs.append(f"날짜 {ad} ≠ 영수증 {rec_date}")
        if aa != R.total.value:
            diffs.append(f"금액 {won(aa)} ≠ 영수증 {won(R.total.value)}")
        add("C6", "첨부철 날짜·금액 기재", UNMET if diffs else MET, "첨부철 기재 날짜·금액 = 영수증",
            "; ".join(diffs) or f"{ad} / {won(aa)}", "영수증 첨부철의 날짜·금액을 영수증과 같게 고쳐 주세요", ev)

    # C7 1인당 한도
    n = len(f.attendees)
    limit = rules.per_person_limit
    if not R.total.value:
        receipt_gap("C7", "1인당 한도", f"결제금액 ÷ 참석 인원 ≤ {won(limit)}", [f.attendees_where.ev()])
    elif n == 0:
        add("C7", "1인당 한도", CHECK, f"결제금액 ÷ 참석 인원 ≤ {won(limit)}", "참석자 이름이 없어 1인당 금액을 계산할 수 없음",
            "참석자 칸에 회의비 사용 인원 전원의 성명을 적어 주세요", [f.attendees_where.ev(), R.total.ev()])
    else:
        per = R.total.value / n
        over = R.total.value - n * limit
        add("C7", "1인당 한도", MET if per <= limit else UNMET, f"결제금액 ÷ 참석 인원 ≤ {won(limit)}",
            f"{won(R.total.value)} ÷ {n}명 = {won(per)}" + (f" (한도 초과 {won(over)})" if over > 0 else ""),
            f"1인당 {won(limit)}을 넘는 금액은 회의비로 인정되지 않습니다", [R.total.ev(), f.attendees_where.ev()])

    # C8 장소 (LLM)
    j = answers.get("C8")
    basis = "회의 장소: 음식점·카페 불가 (강의실·동아리실·회의실 등)"
    if j is None:
        add("C8", "회의 장소", CHECK, basis, "회의 장소를 읽지 못함", "'일시 및 장소' 칸에 장소를 적어 주세요", [f.place.ev()])
    else:
        res = {OK: MET, VIOLATION: UNMET}.get(j.decision, CHECK)
        add("C8", "회의 장소", res, basis, f"장소 '{f.place.value}': {j.reason}",
            "음식점·카페에서 한 회의는 회의비로 인정되지 않습니다" if res == UNMET else "회의 장소를 담당자가 확인",
            [f.place.ev()], j.engine)

    # C9 회의내용 구체성 + 안내문 삭제
    basis = "회의 주제·내용·결과를 구체적으로 기술하고 양식 안내문은 삭제"
    if not content:
        add("C9", "회의내용", UNMET, basis, "회의내용 칸이 비어 있음", "회의내용 칸에 논의 내용과 결과를 구체적으로 적어 주세요", [f.content.ev()])
    elif guide_left:
        add("C9", "회의내용", UNMET, basis, f"양식 안내문이 남아 있음 ('{guide_left[0]}' 등)",
            "회의내용 칸의 ※·▶ 안내 문구를 지우고 실제 회의 내용을 적어 주세요", [f.content.ev()])
    elif not f.topic.value:
        add("C9", "회의내용", UNMET, basis, "회의 주제 칸이 비어 있음", "회의 주제를 적어 주세요", [f.topic.ev()])
    else:
        j = answers["C9"]
        res = {OK: MET, VIOLATION: UNMET}.get(j.decision, CHECK)
        add("C9", "회의내용", res, basis, j.reason,
            "회의에서 논의한 내용과 결정 사항·결과를 구체적으로 보완해 주세요", [f.topic.ev(), f.content.ev()], j.engine)

    # C10 참석자 전원 서명
    basis = "참석자 전원 서명"
    if n == 0:
        add("C10", "참석자 서명", UNMET, basis, "참석자 명단이 비어 있음", "참석자 성명과 서명을 모두 기재해 주세요", [f.attendees_where.ev()])
    else:
        missing = [a.name for a in f.attendees if not a.signed]
        add("C10", "참석자 서명", UNMET if missing else MET, basis,
            f"서명 없음: {', '.join(missing)}" if missing else f"{n}명 전원 서명",
            f"{', '.join(missing)} 학생의 서명을 받아 주세요", [f.attendees_where.ev() | {"value": f"참석 {n}명, 서명 {n - len(missing)}명"}])

    # C11 회의 사진 (코드: 있음 / LLM: 인원·장소)
    basis = "회의 사진 필수, 참석 인원 전원이 나와야 하고 음식점·카페 사진 불가"
    pev = f.photo_field.ev() if f.photo_field.page else {"page": f.minutes_page, "where": "회의비 지출 증빙 '회의 사진' 칸", "value": None}
    if not f.photos:
        if f.loose_images_on_minutes:
            add("C11", "회의 사진", CHECK, basis, "'회의 사진' 칸 밖에 그림이 있음 — 회의 사진인지 확인 필요",
                "회의 사진을 담당자가 확인", [pev])
        else:
            add("C11", "회의 사진", UNMET, basis, "회의 사진이 없음", "참석자 전원이 나온 회의 사진을 '회의 사진' 칸에 넣어 주세요", [pev])
    else:
        j = answers["C11"]
        parts = [f"사진 {len(f.photos)}장"]
        if j.people is not None:
            parts.append(f"사진 속 {j.people}명 / 참석 {n}명")
        if j.decision == VIOLATION:
            res = UNMET
        elif j.people is not None and j.people != n:
            res = UNMET
            parts.append("인원 불일치")
        elif j.decision == OK and j.people == n:
            res = MET
        else:
            res = CHECK
        add("C11", "회의 사진", res, basis, ", ".join(parts) + f" — {j.reason}",
            "회의비 사용 인원 전원이 나오도록, 강의실·회의실 등에서 찍은 사진을 넣어 주세요" if res == UNMET else "사진 속 인원·장소를 담당자가 확인",
            [pev], "코드+" + j.engine)

    # C12 가맹점 주소
    basis = f"가맹점 주소가 {rules.region_label}"
    addr = R.address.value
    if not addr:
        receipt_gap("C12", "가맹점 지역", basis)
    elif any(w.replace(" ", "") in addr.replace(" ", "") for w in rules.region_any_of):
        add("C12", "가맹점 지역", MET, basis, addr, "", [R.address.ev()])
    elif any(w in addr for w in rules.region_ambiguous):
        add("C12", "가맹점 지역", CHECK, basis, f"'{addr}' — 시·도가 없어 {rules.region_label}인지 단정할 수 없음",
            "가맹점 소재지를 담당자가 확인", [R.address.ev()])
    else:
        add("C12", "가맹점 지역", UNMET, basis, f"'{addr}'은(는) {rules.region_label}이 아님",
            f"{rules.region_label} 밖 가맹점 결제분은 회의비로 인정되지 않습니다", [R.address.ev()])

    # C13 결제 시각 20시 이전
    pt = R.time.value
    basis = f"결제 시각 {rules.pay_before:%H:%M} 이전"
    if pt is None:
        receipt_gap("C13", "결제 시각", basis)
    else:
        add("C13", "결제 시각", MET if pt < rules.pay_before else UNMET, basis, f"결제 {pt:%H:%M}",
            f"{rules.pay_before:%H:%M} 이후 결제분은 회의비로 인정되지 않습니다", [R.time.ev()])

    # C14 회의 종료 후 1시간 이내 결제
    lim = rules.max_minutes_after_meeting
    basis = f"회의 종료 후 {lim}분 이내 결제"
    end, start = f.end.value, f.start.value
    if end is None:
        add("C14", "종료 후 결제 시간", CHECK, basis, "회의 종료 시각을 읽지 못함",
            "'일시 및 장소' 칸에 회의 시작·종료 시각을 적어 주세요 (예: 17:00~18:30)", [f.end.ev() if f.end.page else f.meeting_date.ev()])
    elif pt is None:
        receipt_gap("C14", "종료 후 결제 시간", basis, [f.end.ev()])
    else:
        base = meet_date or rec_date or datetime(2000, 1, 1).date()
        e = datetime.combine(base, end)
        if start is not None and end < start:  # 자정을 넘긴 회의
            e += timedelta(days=1)
        paid = datetime.combine(rec_date or base, pt)
        gap = (paid - e).total_seconds() / 60
        s = datetime.combine(base, start) if start else None
        if gap > lim:
            res, msg = UNMET, f"종료 {end:%H:%M} → 결제 {pt:%H:%M} ({gap:.0f}분 후, 기준 {lim}분)"
        elif s is not None and paid < s:
            res, msg = CHECK, f"회의 시작 {start:%H:%M} 전에 결제 ({pt:%H:%M}) — 회의비 결제인지 확인 필요"
        else:
            res, msg = MET, f"종료 {end:%H:%M} → 결제 {pt:%H:%M}" + (f" ({gap:.0f}분 후)" if gap > 0 else " (회의 중 결제)")
        add("C14", "종료 후 결제 시간", res, basis, msg,
            f"회의 종료 후 {lim}분이 지난 결제분은 회의비로 인정되지 않습니다" if res == UNMET else "결제 경위를 담당자가 확인",
            [f.end.ev(), R.time.ev()])

    # C15 카드 결제
    basis = "카드 결제 (현금·계좌이체 불가)"
    method = R.method.value
    if method is None and R.lines:
        method = _method(" ".join(R.lines), rules.card_words, rules.cash_words)
    if not R.present:
        receipt_gap("C15", "결제수단", basis)
    elif method == "card":
        add("C15", "결제수단", MET, basis, "카드 결제", "", [R.method.ev()])
    elif method == "cash":
        add("C15", "결제수단", UNMET, basis, "현금(또는 이체) 결제", "현금·계좌이체 결제분은 회의비로 인정되지 않습니다", [R.method.ev()])
    else:
        add("C15", "결제수단", CHECK, basis, "결제수단을 영수증에서 확인하지 못함", "결제수단을 담당자가 확인", [R.method.ev()])

    # C16 카드번호 표시
    basis = "영수증에 카드번호 표시 (마스킹 포함)"
    if not R.present:
        receipt_gap("C16", "카드번호 표시", basis)
    elif R.card_number.value:
        add("C16", "카드번호 표시", MET, basis, R.card_number.value, "", [R.card_number.ev()])
    else:
        add("C16", "카드번호 표시", UNMET, basis, "영수증에 카드번호가 없음",
            "카드번호가 찍힌 카드 매출전표(또는 카드사 이용내역)를 함께 제출해 주세요",
            [{"page": R.page, "where": f"{R.page}쪽 영수증", "value": None}])

    order = {f"C{i}": i for i in range(1, 17)}
    checks.sort(key=lambda c: order[c.id])
    return checks, engine


def verdict(checks: list[Check]) -> str:
    unmet = [c for c in checks if c.result == UNMET]
    if any(c.severity == "부적합" for c in unmet):
        return "부적합"
    if unmet:
        return "보완필요"
    if any(c.result == CHECK for c in checks):
        return "확인필요"
    return "적합"
