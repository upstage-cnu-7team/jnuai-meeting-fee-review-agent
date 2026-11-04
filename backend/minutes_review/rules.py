"""기준값 설정 파일(rules/*.yaml) 읽기. 기준값을 코드에 박지 않는다."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from pathlib import Path

import yaml

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"


@dataclass
class Rules:
    program: str
    per_person_limit: int
    region_label: str
    region_any_of: list[str]
    region_ambiguous: list[str]
    pay_before: time
    max_minutes_after_meeting: int
    card_words: list[str]
    cash_words: list[str]
    content_min_chars: int
    guide_phrases: list[str]
    severity: dict[str, str] = field(default_factory=dict)
    source: str = ""


def _hm(s: str) -> time:
    h, m = str(s).split(":")
    return time(int(h), int(m))


def load_rules(path: str | Path = "wemeet") -> Rules:
    """'wemeet' / 'club' 같은 이름이나 yaml 파일 경로."""
    p = Path(path)
    if not p.suffix:
        p = RULES_DIR / f"{path}.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    sev = {k: str(v) for k, v in (raw.get("severity") or {}).items()}
    bad = {k: v for k, v in sev.items() if v not in ("부적합", "보완필요", "참고")}
    if bad:
        raise ValueError(f"{p.name}: severity 값은 부적합/보완필요/참고 중 하나여야 합니다: {bad}")
    region = raw["region"]
    return Rules(
        program=str(raw.get("program", p.stem)),
        per_person_limit=int(raw["per_person_limit"]),
        region_label=str(region.get("label", "")),
        region_any_of=list(region["any_of"]),
        region_ambiguous=list(region.get("ambiguous", [])),
        pay_before=_hm(raw["pay_before"]),
        max_minutes_after_meeting=int(raw["max_minutes_after_meeting"]),
        card_words=list(raw["card_words"]),
        cash_words=list(raw["cash_words"]),
        content_min_chars=int(raw.get("content_min_chars", 40)),
        guide_phrases=list(raw.get("guide_phrases", [])),
        severity=sev,
        source=p.name,
    )
