"""양식 확인: 제출 파일이 사업단 '회의비 지출 증빙' 양식(별첨 1-1)인지, 실제 빈 양식 파일과 대조한다.

기준은 손으로 적은 단어 목록이 아니라 빈 양식 HWP(forms/aicollege/별첨1-1_회의비_지출증빙_양식.hwp)를 문서 리더로 읽어 만든다.
- 칸 이름(라벨): 각 행 첫 칸(팀명·회의명·회의일시·회의내용·참석자 명단·영수증·사용 비용·결제자),
  같은 행의 두 번째 라벨(회의장소), 참석자·결제자 표 머리(소속·학번·이름·서명)
- 안내 문구: 빈 양식에 들어 있는 예시 글(팀명 칸의 '팀명', '회의 주제', '활동내용 자세하게 작성', '작성자명' 등).
  제출본에 그대로 남아 있으면 그 칸을 채우지 않은 것이다.
양식 제목의 프로그램 단어(동아리·캡스톤·WE-Meet)는 프로그램마다 다르므로 대조에서 뺀다(team_match가 쓴다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from minutes_review.extract import load
from minutes_review.model import Document

from ..config import BACKEND

TEMPLATE = BACKEND / "forms" / "aicollege" / "별첨1-1_회의비_지출증빙_양식.hwp"
TEMPLATE_WEMEET = BACKEND / "forms" / "aicollege" / "별첨1-1_WE-Meet_회의비_지출증빙_양식(지출서류 묶음).hwp"
MATCH, PARTIAL = 0.9, 0.6  # 칸 이름이 이 비율 이상 있으면 양식 일치 / 일부 일치


def _k(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


@dataclass(frozen=True)
class FormSpec:
    labels: tuple[str, ...]
    placeholders: tuple[tuple[str, str], ...]  # (칸 이름, 빈 양식의 예시 글)


def _parse_template(path, max_tables: int | None = None) -> tuple[list[str], list[tuple[str, str]]]:
    doc = load(path.read_bytes(), path.name)
    labels, placeholders = [], []
    tables = [t for p in doc.pages for t in p.tables][:max_tables]
    for t in tables:
        header_next = False
        for r in t.rows:
            texts = [c.flat for c in r]
            if not any(texts):
                continue
            first = texts[0]
            if len(texts) == 1:  # 제목 행·영수증 행·안내 행
                if first == "영수증":
                    labels.append(first)
                elif first.startswith("영수증 첨부란"):
                    placeholders.append(("영수증", first))
                elif "작성자" in first:  # '작성자 : 작성자명 ( 인 )' / 'O O O'
                    m = re.search(r"작성자\s*:\s*(.+?)\s*\(", first)
                    placeholders.append(("작성자", m[1] if m else "작성자명"))
                continue
            if first in ("참석자 명단", "결제자"):  # 표 머리: 칸 이름 + 소속·학번·이름·서명
                labels += texts
                header_next = first == "참석자 명단"
                continue
            if header_next:  # 참석자 첫 행의 서명 안내 글
                for tx in texts:
                    if tx:
                        placeholders.append(("서명", tx))
                header_next = False
                continue
            if len(texts) >= 2 and first and len(first) <= 8:
                labels.append(first)
                placeholders.append((first, texts[1]))
                if len(texts) >= 4:  # 회의일시 | 값 | 회의장소 | 값
                    labels.append(texts[2])
                    placeholders.append((texts[2], texts[3]))
    return labels, placeholders


@lru_cache
def spec() -> FormSpec:
    """칸 이름은 동아리 양식에서, 예시 글은 동아리·WE-Meet 양식 둘 다에서 뽑는다(칸 구성은 같고 예시 글만 다르다).
    WE-Meet 파일은 지출 서류 묶음이라 앞의 회의비 증빙 표 2개(1~2쪽)만 쓴다."""
    labels, placeholders = _parse_template(TEMPLATE)
    if TEMPLATE_WEMEET.exists():
        _, ph2 = _parse_template(TEMPLATE_WEMEET, max_tables=2)
        placeholders += ph2
    labels = list(dict.fromkeys(labels))
    # 숫자·단위만 있는 예시('원')나 칸 이름과 같은 예시는 남아 있어도 판단 근거가 약해 뺀다.
    # 서명·영수증 칸의 안내 글은 지우지 않고 서명·사진을 붙이는 경우가 많아 '미기재' 근거로 쓰지 않는다.
    ph = [(k, v) for k, v in placeholders if len(_k(v)) >= 3 and k not in ("서명", "영수증")]
    return FormSpec(tuple(labels), tuple(dict.fromkeys(ph)))


@dataclass
class FormResult:
    status: str  # match / partial / none / unknown(글자를 못 읽음)
    ratio: float
    missing: list[str]
    leftover: list[tuple[str, str]]  # 채우지 않은 칸: (칸 이름, 남은 예시 글)

    def student_message(self) -> str:
        """학생 회신용: 채우지 않은 칸만 짚는다."""
        names = ", ".join(k for k, _ in self.leftover)
        return f"양식의 예시 글이 그대로 남아 있습니다({names}). 실제 회의에 맞는 내용으로 채워 다시 제출해 주세요."

    def message(self) -> str:
        if self.status == "unknown":
            return "문서 글자를 읽지 못해 양식을 확인하지 못했습니다. 원본 확인 필요"
        parts = []
        if self.status == "match":
            parts.append(f"사업단 회의비 지출 증빙 양식 (칸 {self.ratio:.0%} 일치)")
        elif self.status == "partial":
            parts.append(f"사업단 양식과 일부 다릅니다. 없는 칸: {', '.join(self.missing)}")
        else:
            parts.append(f"사업단 회의비 지출 증빙 양식이 아닙니다 (칸 {self.ratio:.0%} 일치)")
        if self.leftover:
            parts.append("채우지 않은 칸(양식 예시 글이 그대로 있음): " + ", ".join(f"{k}('{v[:20]}')" for k, v in self.leftover))
        return " / ".join(parts)


def _leftover_in_cells(doc: Document, s: FormSpec) -> list[tuple[str, str]]:
    """예시 글이 '그 칸의 값'으로 남아 있는지 본다. 회의내용 안의 '1. 회의 주제' 같은 소제목을 회의명 예시 글로 오인하지 않게
    (2026-10-31 실제 제출본에서 확인) 문서 전체가 아니라 라벨 다음 칸과 비교한다."""
    values: dict[str, str] = {}
    for p in doc.pages:
        for t in p.tables:
            for r in t.rows:
                texts = [c.flat for c in r]
                for i, tx in enumerate(texts[:-1]):
                    if _k(tx) in {_k(k) for k, _ in s.placeholders}:
                        values.setdefault(_k(tx), _k(texts[i + 1]))
                if len(texts) == 1 and "작성자" in texts[0]:
                    values.setdefault("작성자", _k(texts[0]))
    out = []
    for k, v in s.placeholders:
        cell = values.get(_k(k), "")
        if k == "작성자":
            if _k(v) in cell:
                out.append((k, v))
        elif cell and (cell == _k(v) or (cell.startswith(_k(v)) and len(cell) - len(_k(v)) < 10)):
            out.append((k, v))  # 예시 글 뒤에 실제 내용을 이어 썼으면 채운 것으로 본다
    return out


def _leftover_in_text(text: str, s: FormSpec) -> list[tuple[str, str]]:
    """스캔본(OCR 글자): 라벨 바로 뒤에 예시 글이 붙어 있을 때만 남은 것으로 본다."""
    t = _k(text)
    return [(k, v) for k, v in s.placeholders if (_k(k) + _k(v)) in t or (k == "작성자" and _k(v) in t)]


def check_text(text: str, doc: Document | None = None) -> FormResult:
    s = spec()
    t = _k(text)
    if len(t) < 20:
        return FormResult("unknown", 0.0, [], [])
    found = [lb for lb in s.labels if _k(lb) in t]
    missing = [lb for lb in s.labels if lb not in found]
    ratio = len(found) / len(s.labels)
    status = "match" if ratio >= MATCH else "partial" if ratio >= PARTIAL else "none"
    leftover = [] if status == "none" else (_leftover_in_cells(doc, s) if doc is not None else _leftover_in_text(text, s))
    return FormResult(status, ratio, missing, leftover)


def check_document(doc: Document | None, ocr_text: str | None = None) -> FormResult:
    if ocr_text is not None:
        return check_text(ocr_text)
    if doc is None:
        return FormResult("unknown", 0.0, [], [])
    return check_text("\n".join(p.text for p in doc.pages), doc)
