"""회귀 시험용 Upstage 응답 캐시를 만든다 (UPSTAGE_API_KEY 필요, 호출 비용 발생).

가상 18케이스 × 4형식을 만들고, 캐시에 없는 것만 Upstage에 보낸다.
결과는 tests/fixtures/upstage/<kind>-<key>.json 에 쌓인다. 가상 데이터라 커밋해도 된다.

    cd backend && uv run python tools/build_upstage_fixtures.py
"""
from __future__ import annotations

import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

from aicollege_cases import FIXTURES, build  # noqa: E402
from app.review import upstage  # noqa: E402
from app.review.pipeline import review_file  # noqa: E402
from app.seed import RULES_DIR, rule_set_from_yaml  # noqa: E402


def main():
    rs = rule_set_from_yaml(RULES_DIR / "aicollege_club.yaml", "club")
    rule_set = {"conditions": rs.conditions, "removed": rs.removed}
    cache = upstage.Cache(FIXTURES, use_db=False, write_fixtures=True)
    with tempfile.TemporaryDirectory() as d:
        jobs = build(Path(d))
        # 추출은 초당 1건 간격이 걸려 있어 병렬로 보내도 안전하다
        with ThreadPoolExecutor(6) as ex:
            list(ex.map(lambda j: upstage.extract(j[2].read_bytes(), cache), jobs))
        t0 = time.time()
        wrong = []
        for case, fmt, path in jobs:
            r = review_file(path.read_bytes(), path.name, datetime.fromisoformat(case["submitted_at"]), rule_set, cache)
            unmet = sorted(c["check_id"] for c in r["checks"] if c["result"] == "unmet")
            mark = "OK " if unmet == sorted(case["expect"]) else "XX "
            if mark == "XX ":
                wrong.append(f"{case['name']}.{fmt}")
            print(mark, f"{case['name']}.{fmt}", r["verdict"], "기대", case["expect"], "결과", unmet)
    print(f"Upstage 호출 {cache.misses}건, 판정 {time.time() - t0:.0f}초, 불일치 {len(wrong)}건 {wrong}")


if __name__ == "__main__":
    main()
