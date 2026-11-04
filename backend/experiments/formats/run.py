"""원본 양식 3종 × 정상/위반 × 원본/PDF/DOCX 비교. 변환은 한컴에서 한다.

cd backend && uv run python experiments/formats/run.py generate
cd backend && uv run python experiments/formats/run.py compare
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.aicollege_samples import case, write_hwp  # noqa: E402
from tools.hwpx_filler import write_hwpx  # noqa: E402

FORMS = ROOT / "forms/aicollege"
TEMPLATES = {
    "club": FORMS / "별첨1-1_회의비_지출증빙_양식.hwp",
    "wemeet": FORMS / "별첨1-1_WE-Meet_회의비_지출증빙_양식(지출서류 묶음).hwp",
    "capstone": FORMS / "별첨1_캡스톤디자인_지원비_참고사항_및_증빙자료.hwpx",
}
# 위밋·캡스톤 양식의 10줄 이상 안내도 만족하게 같은 내용을 세 양식에 넣는다.
CONTENT = [
    "1. 사용자 인터뷰 결과 일정 공유와 알림 기능 요청이 가장 많았다.",
    "2. 이번 MVP는 일정 등록, 팀 공유, 마감 알림으로 범위를 정했다.",
    "3. 일정 등록에는 제목, 시작 시각, 종료 시각을 필수로 받기로 했다.",
    "4. 종료 시각이 시작보다 빠르면 저장을 막고 안내하기로 했다.",
    "5. 팀원은 초대 링크로 참여하고 팀 일정만 조회하도록 정했다.",
    "6. 알림은 마감 하루 전 발송하며 중복 발송을 막기로 했다.",
    "7. 김가온과 이나래가 일정 입력 및 목록 화면을 맡기로 했다.",
    "8. 박다솜과 최라온이 일정 API와 알림 처리를 맡기로 했다.",
    "9. 10월 28일까지 화면 설계안을 공유하고 팀원 검토를 받기로 했다.",
    "10. 11월 4일까지 API 초안을 완성하고 다음 회의에서 연동을 점검한다.",
]
CASES = [case("normal", "정상", expect=[], content=CONTENT),
         case("cafe", "회의장소 카페", expect=["R12"], content=CONTENT, place="가온카페 용봉점 2층")]


def inputs(folder: Path, formats=("source", "pdf", "docx")):
    for form, template in TEMPLATES.items():
        for c in CASES:
            source = folder / f"{form}_{c['name']}{template.suffix}"
            yield form, template, c, [source if ext == "source" else source.with_suffix("." + ext) for ext in formats]


def generate(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    for _, template, c, paths in inputs(folder):
        writer = write_hwpx if template.suffix == ".hwpx" else write_hwp
        paths[0].write_bytes(writer(c, template.read_bytes()))
        print(paths[0])


def compare(folder: Path, formats=("source", "pdf", "docx")) -> int:
    # 변환 파일이 없으면 API를 호출하지 않고 누락 목록을 알린다.
    missing = [p for *_, paths in inputs(folder, formats) for p in paths if not p.is_file()]
    if missing:
        print("한컴에서 같은 이름으로 PDF·DOCX를 저장해야 합니다:")
        for p in missing:
            print(p)
        return 2
    from app.review import upstage
    from app.review.pipeline import review_file
    from app.seed import RULES_DIR, rule_set_from_yaml

    rs = rule_set_from_yaml(RULES_DIR / "aicollege_club.yaml", "club")
    rules = {"conditions": rs.conditions, "removed": rs.removed}
    cache = upstage.Cache(folder / "cache", use_db=False, write_fixtures=True)
    rows, failures = [], 0
    for form, _, c, paths in inputs(folder, formats):
        group = []
        for p in paths:
            try:
                result = review_file(p.read_bytes(), p.name, datetime.fromisoformat(c["submitted_at"]), rules, cache)
            except upstage.UpstageError as error:
                failures += 1
                group.append(None)
                rows.append({"file": p.name, "expected_ok": False, "error": str(error)})
                print(p.name, "처리 실패:", error)
                continue
            checks = {x["check_id"]: x["result"] for x in result["checks"]}
            unmet = sorted(k for k, v in checks.items() if v == "unmet")
            expected_verdict = "reject" if c["expect"] else "pass"
            good = unmet == c["expect"] and result["verdict"] == expected_verdict
            failures += not good
            group.append(checks)
            rows.append({"file": p.name, "expected_unmet": c["expect"], "unmet": unmet,
                         "verdict": result["verdict"], "expected_ok": good, "checks": checks})
            print(p.name, result["verdict"], "미충족", unmet)
        equal = all(checks is not None for checks in group) and all(checks == group[0] for checks in group[1:])
        failures += not equal
        print(f"{form}/{c['name']}: 전체 항목 형식 간 일치={equal}")
    report = "results.json" if len(formats) == 3 else "results_" + "_".join(formats) + ".json"
    (folder / report).write_text(json.dumps({"formats": list(formats), "full_matrix": len(formats) == 3,
        "provisional_rules": "aicollege_club.yaml",
        "failures": failures, "rows": rows}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["generate", "compare"])
    parser.add_argument("--folder", type=Path, default=ROOT / "out/formats")
    parser.add_argument("--formats", nargs="+", choices=["source", "pdf", "docx"], default=["source", "pdf", "docx"])
    args = parser.parse_args()
    if args.mode == "generate":
        generate(args.folder)
    else:
        raise SystemExit(compare(args.folder, tuple(dict.fromkeys(args.formats))))
