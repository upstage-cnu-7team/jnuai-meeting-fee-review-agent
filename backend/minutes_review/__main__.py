"""python -m minutes_review 회의록.hwp [영수증.pdf ...] [--rules wemeet|club|경로] [--offline]"""
from __future__ import annotations

import argparse
import json
import sys

from . import review_paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="minutes_review", description="회의비 증빙(회의록+영수증) 검수")
    ap.add_argument("files", nargs="+", help="HWP·HWPX·PDF·DOCX (여러 개면 한 건으로 합쳐 검수)")
    ap.add_argument("--rules", default="wemeet", help="기준값: wemeet / club / yaml 경로 (기본 wemeet)")
    ap.add_argument("--offline", action="store_true", help="Claude를 쓰지 않고 규칙으로만 판단")
    ap.add_argument("--draft", action="store_true", help="JSON 대신 보완 요청 초안 본문만 출력")
    a = ap.parse_args(argv)
    result = review_paths(a.files, rules=a.rules, use_llm=not a.offline)
    if a.draft:
        print(result["draft"]["subject"], result["draft"]["body"], sep="\n\n")
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
