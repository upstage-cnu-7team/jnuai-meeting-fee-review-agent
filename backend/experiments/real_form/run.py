"""실제 양식 실험 실행: 케이스마다 사업단 빈 양식 HWP에 값을 채워 서비스 판정 코드(app/review)로 끝까지 돌리고 기대와 비교한다.

Upstage(Information Extract·Solar·OCR)를 실제로 부른다. 응답은 cache/에 쌓여 다시 돌리면 호출하지 않는다(가상 데이터라 커밋 가능).

    cd backend && uv run python experiments/real_form/run.py            # 결과: experiments/real_form/results.md
    uv run python experiments/real_form/run.py R09                      # 이름에 R09가 들어간 케이스만
"""
from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from cases import CASES  # noqa: E402

from app.review import upstage  # noqa: E402
from app.review.pipeline import review_file  # noqa: E402
from app.seed import RULES_DIR, rule_set_from_yaml  # noqa: E402
from tools.aicollege_samples import write_hwp  # noqa: E402

TEMPLATE = ROOT / "forms" / "aicollege" / "별첨1-1_회의비_지출증빙_양식.hwp"
OUT = HERE / "files"
CACHE = HERE / "cache"


def main(only: str | None):
    rs = rule_set_from_yaml(RULES_DIR / "aicollege_club.yaml", "club")
    rule_set = {"conditions": rs.conditions, "removed": rs.removed}
    cache = upstage.Cache(CACHE, use_db=False, write_fixtures=True)
    OUT.mkdir(exist_ok=True)
    cases = [c for c in CASES if not only or only in c["name"]]
    tpl = TEMPLATE.read_bytes()
    files = []
    for c in cases:
        p = OUT / f"{c['name']}.hwp"
        p.write_bytes(write_hwp(c, tpl))
        files.append(p)
    t0 = time.time()
    with ThreadPoolExecutor(6) as ex:  # 추출 먼저 (초당 1건 간격은 upstage.py가 맞춘다)
        list(ex.map(lambda p: upstage.extract(p.read_bytes(), cache), files))
    rows, ok = [], 0
    for c, p in zip(cases, files):
        data = p.read_bytes()
        r = review_file(data, p.name, datetime.fromisoformat(c["submitted_at"]), rule_set, cache)
        res = {x["check_id"]: x for x in r["checks"]}
        unmet = sorted(k for k, x in res.items() if x["result"] == "unmet")
        review = sorted(k for k, x in res.items() if x["result"] == "review")
        good = unmet == c["expect"] and all(k in review for k in c["review"])
        ok += good
        detail = "; ".join(f"{k} {res[k]['message']}" for k in unmet + review)
        rows.append(f"| {'✅' if good else '❌'} | {c['name']} | {c['note']} | {','.join(c['expect']) or '-'}"
                    f"{' / 확인필요 ' + ','.join(c['review']) if c['review'] else ''} | {','.join(unmet) or '-'}"
                    f" | {','.join(review) or '-'} | {r['verdict']} | {detail.replace('|', '/')[:300]} |")
        print(("OK " if good else "XX ") + c["name"], "기대", c["expect"], c["review"], "→ 미충족", unmet, "확인필요", review)
    head = (f"# 실제 양식 실험 결과\n\n- 실행: {datetime.now():%Y-%m-%d %H:%M}, 케이스 {len(cases)}개, 기대대로 {ok}개\n"
            f"- 양식: `forms/aicollege/별첨1-1_회의비_지출증빙_양식.hwp`(사업단 원본)에 값을 채운 HWP\n"
            f"- 판정: 서비스 코드(`app/review`) + Upstage Information Extract · solar-pro4 · 양식 확인(F00)\n"
            f"- Upstage 실제 호출 {cache.misses}건, {time.time() - t0:.0f}초\n\n"
            "| | 케이스 | 내용 | 기대(미충족 / 확인필요) | 결과 미충족 | 결과 확인필요 | 판정 | 근거 |\n|---|---|---|---|---|---|---|---|\n")
    if not only:
        (HERE / "results.md").write_text(head + "\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n기대대로 {ok}/{len(cases)}, Upstage 호출 {cache.misses}건")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
