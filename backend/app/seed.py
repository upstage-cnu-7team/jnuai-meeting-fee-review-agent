"""첫 실행 때 기본 데이터를 넣는다: 계정(.env 비밀번호), 팀(rules/teams.yaml), 확정 기준(rules/aicollege_club.yaml).

이미 있으면 건드리지 않는다. 판정 기준은 DB `rule_sets`가 정본이고 yaml은 seed일 뿐이다.
"""
from __future__ import annotations

from datetime import datetime

import yaml
from sqlalchemy import func, select

from .config import BACKEND, get_settings
from .db import session
from .models import PROGRAMS, RuleSet, Team, User
from .security import hash_password

RULES_DIR = BACKEND / "rules"

ACCOUNTS = [  # (username, 이름, role, programs, mailbox, 비밀번호 설정 이름)
    ("club-manager", "동아리 담당자", "manager", ["club", "aim", "hackathon"], "club_manager", "seed_password_club"),
    ("wemeet-manager", "위밋 담당자", "manager", ["wemeet", "capstone"], "wemeet_manager", "seed_password_wemeet"),
    ("admin", "관리자", "admin", PROGRAMS, None, "seed_password_admin"),
]

# yaml 표기 → API 값
SEVERITY = {"부적합": "reject", "보완필요": "needs_fix"}
BY = {"코드": "code", "Solar": "ai", "Solar+코드": "ai", "Extract+코드": "extract+code", "코드(접수 일시)": "code"}


def rule_set_from_yaml(path, program: str, version: int = 1) -> RuleSet:
    y = yaml.safe_load(path.read_text(encoding="utf-8"))
    conds = []
    for c in y["conditions"]:
        conds.append({**c, "by": BY.get(c["by"], "code"), "severity": SEVERITY.get(c["severity"], "needs_fix"),
                      "by_label": c["by"], "enabled": True})
    removed = [{"id": r["id"], "name": r["name"], "enabled": False, "excluded_reason": r.get("reason")} for r in y.get("removed") or []]
    return RuleSet(id=f"rs_{program}_v{version}", program=program, version=version, status=y.get("status", "draft"),
                   conditions=conds, removed=removed, confirmed_by="동아리 담당자" if y.get("status") == "confirmed" else None,
                   confirmed_at=datetime(2026, 10, 28, 11, 0) if y.get("status") == "confirmed" else None)


def seed_basics():
    s = get_settings()
    with session() as db:
        for username, name, role, programs, mailbox, pw_attr in ACCOUNTS:
            pw = getattr(s, pw_attr)
            if pw and db.scalar(select(User).where(User.username == username)) is None:
                db.add(User(username=username, password_hash=hash_password(pw), name=name, role=role, programs=programs, mailbox=mailbox))

        if db.scalar(select(Team).limit(1)) is None:
            data = yaml.safe_load((RULES_DIR / "teams.yaml").read_text(encoding="utf-8"))
            for program in PROGRAMS:
                for i, t in enumerate(data["programs"].get(program) or [], 1):
                    db.add(Team(id=f"t_{program}_{i:03d}", program=program, name=t["name"], aliases=list(t.get("aliases") or []),
                                strict=bool(t.get("strict")), members=list(t.get("members") or [])))

        else:  # 팀원 명단은 yaml에 나중에 채운다 → 비어 있는 DB 명단만 yaml로 채운다
            data = yaml.safe_load((RULES_DIR / "teams.yaml").read_text(encoding="utf-8"))
            for program in PROGRAMS:
                for t in data["programs"].get(program) or []:
                    if t.get("members"):
                        row = db.scalar(select(Team).where(Team.program == program, Team.name == t["name"]))
                        if row is not None and not row.members:
                            row.members = list(t["members"])

        y_ver = int(yaml.safe_load((RULES_DIR / "aicollege_club.yaml").read_text(encoding="utf-8")).get("version") or 1)
        cur = db.scalar(select(func.max(RuleSet.version)).where(RuleSet.program == "club"))
        if cur is None or cur < y_ver:  # yaml 기준이 올라가면 새 버전으로 더한다 (이전 판정의 기준 버전은 그대로 남음)
            db.add(rule_set_from_yaml(RULES_DIR / "aicollege_club.yaml", "club", version=y_ver))
        db.commit()
