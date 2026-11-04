"""프로그램·팀 정하기 (rules/teams.yaml 머리말, 2026-10-31 종희 확인).

프로그램
  1) 별첨 제목 단어: 캡스톤 → capstone, 동아리 → club, WE-Meet → wemeet
  2) 제목 단어가 없는 양식 = AIM 챌린지 또는 해커톤(둘 다 동아리 담당자). 두 팀 목록에서 팀명으로 정한다.
     두 곳에 다 있는 팀(테라바이트)은 회의록 참석자 이름을 팀원 명단(members)과 대조한다.
     못 정하면 프로그램 미확정으로 두고 이유를 담당자 화면에 띄운다.
  3) 양식 글자가 없으면(못 읽음) 담당자 메일함·메일 단어로 좁힌다.
팀: 회의록 팀명(가장 믿음) → 메일 제목·본문·첨부 파일명. 긴 키 우선.
    strict 팀(흔한 단어·짧은 이름)은 메일 글자만으로는 확정하지 않는다.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from ..config import BACKEND

sys.path.insert(0, str(BACKEND))
from tools.team_keys import keys_of, normalize  # noqa: E402

NAMES = {"club": "동아리", "aim": "AIM 챌린지", "hackathon": "해커톤", "wemeet": "위밋", "capstone": "캡스톤"}


@lru_cache
def _cfg() -> dict:
    return yaml.safe_load((BACKEND / "rules" / "teams.yaml").read_text(encoding="utf-8"))


def mailbox_programs(mailbox: str | None) -> list[str]:
    return list(_cfg()["mailboxes"].get(mailbox or "", []))


def program_from_form_title(text: str) -> str | None:
    """양식 첫머리(별첨 제목)에서 프로그램 단어를 찾는다. AIM·해커톤은 제목 단어가 없어 None."""
    head = normalize(text[:300])
    for program, spec in _cfg()["form_titles"].items():
        if any(normalize(w) in head for w in spec["words"]):
            return program
    return None


def program_from_mail(text: str) -> list[str]:
    t = normalize(text)
    return [p for p, words in _cfg()["mail_words"].items() if any(normalize(w) in t for w in words)]


@dataclass
class TeamCandidate:
    id: str
    name: str
    aliases: list
    strict: bool
    members: list = field(default_factory=list)


def match_team(teams: list[TeamCandidate], form_team_name: str | None, mail_text: str) -> tuple[str | None, str]:
    """→ (team_id | None, 이유). 같은 프로그램 안의 팀 목록만 넘긴다."""
    form = normalize(form_team_name or "")
    mail = normalize(mail_text)
    best: tuple[int, int, TeamCandidate, str] | None = None  # (출처 점수, 키 길이, 팀, 이유)
    for t in teams:
        keys = keys_of({"name": t.name, "aliases": t.aliases})
        if form:
            if form in keys:
                cand = (3, len(form), t, "회의록 팀명 일치")
            elif any(len(k) >= 3 and k in form for k in keys):
                cand = (2, max(len(k) for k in keys if k in form), t, "회의록 팀명에 팀 이름 포함")
            else:
                cand = None
            if cand and (best is None or cand[:2] > best[:2]):
                best = cand
        hits = [k for k in keys if k in mail]
        if hits:
            if t.strict and not any(k == normalize(re.sub(r"\([^)]*\)", "", t.name)) and len(k) >= 4 for k in hits):
                continue  # 흔한 단어·짧은 이름이 메일 글자에만 맞음 → 확정하지 않음
            cand = (1, max(len(k) for k in hits), t, "메일 제목·본문·파일명에 팀 이름")
            if best is None or cand[:2] > best[:2]:
                best = cand
    if best is None:
        return None, f"회의록 팀명 '{form_team_name}'과 일치하는 팀 없음" if form else "일치하는 팀 없음"
    if form and best[0] == 1:
        # 회의록에 팀명이 있는데 팀 목록에 없고 메일 글자만 맞음 → 회의록을 믿고 확정하지 않는다
        return None, f"회의록 팀명 '{form_team_name}'이 팀 목록에 없음 (메일에는 '{best[2].name}')"
    return best[2].id, best[3]


@dataclass
class Decision:
    program: str | None
    program_reason: str
    team_id: str | None
    team_reason: str
    alert: str | None = None  # 담당자 화면에 띄울 안내 (미확정 이유 등)


def _by_roster(hits: dict[str, tuple[str, TeamCandidate]], attendees: list[str]) -> tuple[str | None, str]:
    """같은 이름 팀이 여러 프로그램에 있을 때 참석자 이름과 팀원 명단을 대조한다."""
    people = {normalize(a) for a in attendees if a}
    overlap = {p: len(people & {normalize(m) for m in t.members}) for p, (_, t) in hits.items()}
    if not any(t.members for _, t in hits.values()):
        return None, "팀원 명단이 아직 등록되지 않았습니다"
    if sum(n > 0 for n in overlap.values()) > 1:
        return None, "참석자에 두 프로그램의 팀원이 함께 있어 담당자 확인이 필요합니다"
    best = max(overlap.values())
    winners = [p for p, n in overlap.items() if n == best]
    if best == 0:
        return None, "참석자가 어느 팀원 명단과도 겹치지 않습니다"
    if len(winners) > 1:
        return None, "참석자가 두 팀원 명단과 똑같이 겹칩니다"
    return winners[0], f"참석자 {best}명이 {NAMES[winners[0]]} 팀원 명단과 일치"


def decide(form_text: str, mailbox: str | None, mail_text: str, form_team_name: str | None, attendees: list[str],
           teams_by_program: dict[str, list[TeamCandidate]]) -> Decision:
    allowed = mailbox_programs(mailbox) or list(NAMES)
    title = program_from_form_title(form_text) if form_text else None
    mail_programs = program_from_mail(mail_text)

    def cross_check(d: Decision) -> Decision:
        if d.program and mail_programs:
            if d.team_id and d.team_reason.startswith("회의록 팀명"):
                # 회의록 양식 칸의 팀명으로 팀을 찾았으면 그대로 확정한다. 메일 제목·파일명 표기는 1차 단서일 뿐이라 안내를 띄우지 않는다 (2026-11-02 종희)
                d.program_reason += " / 회의록 팀명으로 확정"
            elif d.program not in mail_programs or len(mail_programs) > 1:
                words = "·".join(NAMES[p] for p in mail_programs)
                warning = f"메일 프로그램 표기({words})와 양식·팀 판단({NAMES[d.program]})을 교차 확인해 주세요."
                d.alert = " ".join(x for x in (d.alert, warning) if x)
                d.program_reason += " / 메일 프로그램 표기와 충돌·복수 표기"
            else:
                d.program_reason += " / 메일 제목·본문 프로그램 표기 일치"
        return d

    def team_in(program: str, reason: str, alert: str | None = None) -> Decision:
        tid, tr = match_team(teams_by_program.get(program, []), form_team_name, mail_text)
        if tid is None and form_team_name:
            alert = " ".join(x for x in [alert, f"{tr}. 팀을 지정해 주세요."] if x)
        return cross_check(Decision(program, reason, tid, tr, alert))

    if title:
        # 별첨 제목이 가장 믿을 만하다. 다른 담당자 메일함으로 왔어도 양식대로 정하고 알린다
        if mailbox and title not in allowed:
            box = "·".join(NAMES[p] for p in allowed)
            return team_in(title, "회의록 별첨 제목", f"{box} 담당자 메일함으로 왔지만 회의록은 {NAMES[title]} 양식입니다.")
        return team_in(title, "회의록 별첨 제목")

    title_less = [p for p in _cfg().get("title_less_programs", []) if p in allowed]
    if form_text and title is None and title_less:
        # 제목 단어 없는 양식 → AIM·해커톤 중 팀명으로
        hits = {}
        for p in title_less:
            tid, tr = match_team(teams_by_program.get(p, []), form_team_name, mail_text)
            if tid:
                hits[p] = (tr, next(t for t in teams_by_program[p] if t.id == tid))
        if len(hits) == 1:
            p, (tr, t) = next(iter(hits.items()))
            return cross_check(Decision(p, f"제목에 프로그램 단어 없음 → {NAMES[p]} 팀 목록에서 찾음", t.id, tr))
        if len(hits) > 1:
            team_name = next(iter(hits.values()))[1].name
            p, why = _by_roster(hits, attendees)
            if p:
                return cross_check(Decision(p, why, hits[p][1].id, hits[p][0]))
            both = "·".join(NAMES[x] for x in hits)
            return Decision(None, f"{team_name}: {both} 모두에 있는 팀", None, "프로그램 미확정",
                            alert=f"'{team_name}' 팀은 {both}에 모두 있습니다. {why}. 프로그램과 팀을 지정해 주세요.")
        if len(title_less) == 1:
            return team_in(title_less[0], "제목에 프로그램 단어 없음")
        words = [p for p in program_from_mail(mail_text) if p in title_less]
        if len(words) == 1:
            return team_in(words[0], "메일 제목·본문의 프로그램 단어")
        return Decision(None, "제목에 프로그램 단어가 없고 팀도 찾지 못함", None, "프로그램 미확정",
                        alert="회의록 제목에 프로그램 이름이 없고 AIM 챌린지·해커톤 팀 목록에서도 팀을 찾지 못했습니다. 프로그램과 팀을 지정해 주세요.")

    # 양식 글자를 못 읽음(첨부 없음 포함) → 메일 제목·본문·파일명의 팀명으로 프로그램을 찾는다 (2026-11-02 종희)
    words = [p for p in program_from_mail(mail_text) if p in allowed]
    found = {}
    for p in allowed:
        tid, tr = match_team(teams_by_program.get(p, []), None, mail_text)
        if tid:
            found[p] = (tid, tr)
    if words:  # 프로그램 단어가 있으면 그 안에서 찾은 팀을 우선
        found = {p: v for p, v in found.items() if p in words} or found
    if len(found) == 1:
        p, (tid, tr) = next(iter(found.items()))
        return Decision(p, f"메일 제목·본문의 팀명 → {NAMES[p]}", tid, tr)
    if len(allowed) == 1:
        return team_in(allowed[0], "담당자 메일함")
    if len(words) == 1:
        return team_in(words[0], "메일 제목·본문의 프로그램 단어")
    return Decision(None, "프로그램을 정할 수 없음", None, "프로그램 미확정",
                    alert="회의록에서 프로그램을 알아보지 못했습니다. 프로그램과 팀을 지정해 주세요.")
