"""rules/teams.yaml의 팀명에서 메일 필터·팀 매칭용 비교 키를 만든다.

    uv run python tools/team_keys.py            # 팀별 키 목록
    uv run python tools/team_keys.py --json     # Power Automate '작성' 단계에 붙일 키 배열(JSON)
    uv run python tools/team_keys.py --json --mailbox club_manager   # 담당자 한 명이 맡은 프로그램 키만
    uv run python tools/team_keys.py --owa --mailbox club_manager    # OWA 규칙용: 정규화 키 + 원래 표기(소문자), 한 줄에 하나

규칙
- 소문자로 바꾸고 공백 _ - , . 를 지운다.
- 괄호 안 이름은 따로 하나의 이름으로 본다. AI-GO(아이고) → aigo, 아이고 / 으라차차아이(AI)키키 → 으라차차아이키키, ai
  (괄호 안이 2글자 이하이면 따로 쓰지 않는다.)
- 한글이 든 이름: 6글자 이상이면 4글자씩 연속 조각도 키. 영어 이름: 8글자 이상이면 6글자씩 연속 조각도 키.
  그보다 짧으면 전체 이름만.
- aliases(줄임말)는 손으로 넣은 그대로 정규화만 해서 키에 더한다.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

TEAMS = Path(__file__).resolve().parents[1] / "rules" / "teams.yaml"
HANGUL = re.compile(r"[가-힣]")


def normalize(text: str) -> str:
    return re.sub(r"[\s_\-,.()]", "", text.lower())


def names_of(team_name: str) -> list[str]:
    """팀명 → 정규화된 이름들 (괄호 밖 이름 + 괄호 안 이름)."""
    inner = [m for m in re.findall(r"\(([^)]*)\)", team_name) if len(normalize(m)) > 2]
    outer = re.sub(r"\([^)]*\)", "", team_name)
    return [n for n in dict.fromkeys(normalize(x) for x in [outer, *inner]) if n]


def windows(name: str) -> list[str]:
    size, min_len = (4, 6) if HANGUL.search(name) else (6, 8)
    if len(name) < min_len:
        return []
    return [name[i:i + size] for i in range(len(name) - size + 1)]


def keys_of(team: dict) -> list[str]:
    keys = []
    for n in names_of(team["name"]):
        keys += [n, *windows(n)]
    keys += [normalize(a) for a in team.get("aliases") or []]
    return list(dict.fromkeys(k for k in keys if k))


def load(mailbox: str | None = None) -> dict[str, list[dict]]:
    data = yaml.safe_load(TEAMS.read_text())
    programs = data["programs"]
    if mailbox:
        programs = {p: programs[p] for p in data["mailboxes"][mailbox]}
    return programs


def main():
    mailbox = sys.argv[sys.argv.index("--mailbox") + 1] if "--mailbox" in sys.argv else None
    programs = load(mailbox)
    if "--owa" in sys.argv:
        words = []
        for teams in programs.values():
            for t in teams:
                outer = re.sub(r"\([^)]*\)", "", t["name"]).strip()
                inner = [m.strip() for m in re.findall(r"\(([^)]*)\)", t["name"]) if len(m.strip()) > 2]
                words += [w.lower() for w in [outer, *inner]] + keys_of(t)
        print("\n".join(dict.fromkeys(w for w in words if w)))
        return
    if "--json" in sys.argv:
        all_keys = sorted({k for teams in programs.values() for t in teams for k in keys_of(t)}, key=lambda k: (-len(k), k))
        print(json.dumps(all_keys, ensure_ascii=False))
        return
    for program, teams in programs.items():
        print(f"[{program}] {len(teams)}팀")
        for t in teams:
            print(f"  {t['name']:<22} {', '.join(keys_of(t))}")


if __name__ == "__main__":
    main()
