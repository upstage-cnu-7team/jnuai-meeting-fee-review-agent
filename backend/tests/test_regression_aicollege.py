"""실험 회귀(72건): 가상 18케이스 × hwp·pdf·docx·scan이 기대한 조건에서만 미충족이 나오는지.

Upstage 응답은 tests/fixtures/upstage/의 캐시를 쓴다(키 없이 오프라인). 캐시가 없으면 건너뛴다.
캐시 만들기(키 필요, 호출 비용 발생): `uv run python tools/build_upstage_fixtures.py`
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from aicollege_cases import FIXTURES, build
from app.review import upstage
from app.review.pipeline import review_file
from app.seed import RULES_DIR, rule_set_from_yaml

pytestmark = pytest.mark.skipif(not any(FIXTURES.glob("ie-*.json")), reason="Upstage fixture 없음: tools/build_upstage_fixtures.py로 만든다")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    rs = rule_set_from_yaml(RULES_DIR / "aicollege_club.yaml", "club")
    rule_set = {"conditions": rs.conditions, "removed": rs.removed}
    cache = upstage.Cache(FIXTURES, use_db=False)
    out = {}
    for case, fmt, path in build(tmp_path_factory.mktemp("cases")):
        submitted = datetime.fromisoformat(case["submitted_at"])
        out[(case["name"], fmt)] = (case, review_file(path.read_bytes(), path.name, submitted, rule_set, cache))
    assert cache.misses == 0, "fixture에 없는 Upstage 호출이 있었다 (케이스 파일이 바뀌었으면 fixture를 다시 만든다)"
    return out


def test_72_cases_flag_only_expected_conditions(results):
    wrong = []
    for (name, fmt), (case, r) in sorted(results.items()):
        unmet = sorted(c["check_id"] for c in r["checks"] if c["result"] == "unmet")
        if unmet != sorted(case["expect"]):
            wrong.append(f"{name}.{fmt}: 기대 {case['expect']} / 결과 {unmet}")
    assert len(results) == 72
    assert not wrong, "\n".join(wrong)


def test_formats_never_contradict(results):
    """같은 케이스를 형식만 바꿨을 때 한 형식은 충족, 다른 형식은 미충족이면 안 된다.
    한쪽만 확인필요인 것은 허용한다(추출이 값 하나를 못 읽은 경우 — 원칙대로 담당자 확인으로 넘어간 것).
    2026-10-31 실행: A10 hwp에서 카드종류를 못 읽어 R02 확인필요 1건."""
    by_case: dict[str, dict] = {}
    for (name, fmt), (_, r) in results.items():
        for c in r["checks"]:
            by_case.setdefault((name, c["check_id"]), {})[fmt] = c["result"]
    contradict = [k for k, v in by_case.items() if {"met", "unmet"} <= set(v.values())]
    soft = [k for k, v in by_case.items() if len(set(v.values())) > 1]
    print(f"형식 간 확인필요 차이 {len(soft)}건: {soft}")
    assert not contradict, contradict
    assert len(soft) <= 3, soft


def test_excluded_conditions_listed(results):
    _, r = results[("A01_정상", "pdf")]
    excluded = [c["check_id"] for c in r["checks"] if c["result"] == "excluded"]
    assert excluded == ["R18", "R19", "R20"]
    assert r["verdict"] in ("pass", "review")


def test_all_72_files_match_real_form(tmp_path):
    """가상 회의록 72개가 모두 사업단 빈 양식(별첨 1-1)과 칸이 일치한다. 스캔본은 OCR 글자로 본다."""
    from app.review import readers
    from app.review.form_check import check_document

    cache = upstage.Cache(FIXTURES, use_db=False)
    bad = []
    for case, fmt, path in build(tmp_path):
        data = path.read_bytes()
        fmt2, doc = readers.classify(data, path.name)
        ocr = upstage.ocr(data, path.name, cache)["text"] if fmt2 == "scan" else None
        r = check_document(doc, ocr)
        if r.status != "match" or r.leftover:
            bad.append(f"{case['name']}.{fmt}: {r.message()}")
    assert cache.misses == 0 and not bad, bad
