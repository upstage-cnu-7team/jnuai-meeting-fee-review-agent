"""회의비 증빙(회의록 + 영수증) 검수 핵심 로직. 프레임워크(LangGraph·FastAPI)에 의존하지 않는다.

    from minutes_review import review_files
    result = review_files([("회의록.hwp", data)], rules="wemeet")   # → JSON 직렬화 가능한 dict
"""
from __future__ import annotations

from pathlib import Path

from .checks import run_checks, verdict
from .draft import make_draft
from .extract import load
from .fields import extract_fields
from .judge import Judge, default_judge
from .model import Document, Page
from .rules import Rules, load_rules

__all__ = ["review_files", "review_paths", "merge_documents", "load_rules"]


def merge_documents(docs: list[Document]) -> Document:
    """여러 파일(회의록 HWP + 영수증 PDF 등)을 쪽 번호를 이어 붙인 한 문서로."""
    if len(docs) == 1:
        return docs[0]
    pages, warnings, n = [], [], 0
    for d in docs:
        for p in d.pages:
            n += 1
            pages.append(Page(n, p.body, p.tables, p.loose_images))
        warnings += [f"{d.filename}: {w}" for w in d.warnings]
    kinds = {d.kind for d in docs}
    return Document(kinds.pop() if len(kinds) == 1 else "mixed", ", ".join(d.filename for d in docs), pages, warnings)


def review_files(files: list[tuple[str, bytes]], rules: str | Path | Rules = "wemeet", judge: Judge | None = None,
                 use_llm: bool = True) -> dict:
    rules = rules if isinstance(rules, Rules) else load_rules(rules)
    judge = judge or default_judge(rules.content_min_chars, use_llm)
    docs = [load(data, name) for name, data in files]
    doc = merge_documents(docs)
    fields = extract_fields(doc, rules.guide_phrases, judge.assist_datetime_place)
    checks, engine = run_checks(fields, rules, judge)
    v = verdict(checks)
    return {
        "verdict": v,
        "rules": rules.source,
        "engine": engine,
        "sources": [{"file": d.filename, "kind": d.kind, "pages": len(d.pages), "needs_ocr": d.needs_ocr} for d in docs],
        "warnings": doc.warnings + fields.notes,
        "checks": [c.to_dict() for c in checks],
        "fields": fields.to_dict(),
        "draft": make_draft(checks, v, fields.club_name.value, fields.round.value),
    }


def review_paths(paths: list[str | Path], **kw) -> dict:
    return review_files([(Path(p).name, Path(p).read_bytes()) for p in paths], **kw)
