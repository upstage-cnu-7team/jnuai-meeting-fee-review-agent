"""항목 결과 → 종합 판정. 우선순위 reject > needs_fix > review > pass (frontend-api.md 2-2)."""
from __future__ import annotations

from .conditions import REVIEW, UNMET


def verdict(checks: list[dict]) -> str:
    unmet = [c for c in checks if c["result"] == UNMET]
    if any(c["severity"] == "reject" for c in unmet):
        return "reject"
    if unmet:
        return "needs_fix"
    if any(c["result"] == REVIEW for c in checks):
        return "review"
    return "pass"
