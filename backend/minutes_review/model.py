"""형식(PDF·DOCX·HWP·HWPX)과 무관한 문서 중간 표현.

모든 리더는 파일을 `Document`(쪽 목록)로 바꾼다. 쪽마다 표 밖 본문 텍스트, 표(행 → 칸), 그림 정보가 들어간다.
- 표의 병합 칸은 한 번만 나온다 (빈 자리 None을 넣지 않는다). 그래서 "라벨 칸 → 다음 칸" 규칙이 형식과 무관하게 통한다.
- HWP·DOCX는 쪽 배치 정보가 파일에 없어 '쪽 나누기' 위치로 쪽을 나눈다 (PDF와 같은 위치에 쪽 나누기가 있으면 쪽 번호가 같다).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


def norm(text: str | None) -> str:
    """공백을 한 칸으로 줄인 텍스트. 형식마다 다른 줄바꿈·공백 차이를 없앤다."""
    return re.sub(r"\s+", " ", text or "").strip()


def key(text: str | None) -> str:
    """라벨 비교용: 공백을 모두 지운 텍스트 ('일시 및 장소' == '일시및장소')."""
    return re.sub(r"\s+", "", text or "")


@dataclass
class Image:
    """그림 한 개. data는 비전 판독(사진 속 인원)에 쓸 원본 바이트이며 못 꺼내면 None."""

    data: bytes | None = None
    mime: str | None = None


@dataclass
class Cell:
    text: str
    images: list[Image] = field(default_factory=list)

    def __post_init__(self):
        # 줄 구조는 남기고(영수증처럼 줄 단위로 읽어야 하는 칸) 줄 안의 공백만 정리
        self.text = "\n".join(norm(ln) for ln in (self.text or "").splitlines() if norm(ln))

    @property
    def flat(self) -> str:
        """한 줄로 편 텍스트. PDF는 칸 너비에 따라 줄이 바뀌므로 값 비교·출력은 이것을 쓴다."""
        return norm(self.text)


@dataclass
class Table:
    rows: list[list[Cell]]

    def texts(self) -> list[list[str]]:
        return [[c.flat for c in row] for row in self.rows]


@dataclass
class Page:
    no: int  # 사람용 쪽 번호 (1부터)
    body: str = ""  # 표 밖 본문 텍스트 (줄 단위)
    tables: list[Table] = field(default_factory=list)
    loose_images: list[Image] = field(default_factory=list)  # 표 칸 밖 그림

    @property
    def body_lines(self) -> list[str]:
        return [norm(ln) for ln in self.body.splitlines() if norm(ln)]

    @property
    def image_count(self) -> int:
        return len(self.loose_images) + sum(len(c.images) for t in self.tables for r in t.rows for c in r)

    @property
    def text(self) -> str:
        """쪽 전체 텍스트 (본문 + 표 칸)."""
        cells = [c.flat for t in self.tables for r in t.rows for c in r if c.text]
        return "\n".join(self.body_lines + cells)


@dataclass
class Document:
    kind: str  # 'pdf' / 'docx' / 'hwp' / 'hwpx' / 'image'
    filename: str
    pages: list[Page]
    warnings: list[str] = field(default_factory=list)

    @property
    def needs_ocr(self) -> bool:
        """글자 없이 그림만 있는 쪽이 있으면 스캔본·사진으로 본다 (OCR은 범위 밖 → 확인필요)."""
        return any(not p.text.strip() and p.image_count for p in self.pages)
