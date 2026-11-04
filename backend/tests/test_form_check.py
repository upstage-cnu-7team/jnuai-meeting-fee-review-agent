"""양식 확인: 빈 양식 HWP에서 칸 구조를 뽑아 제출본과 대조."""
from pathlib import Path

from app.review import readers
from app.review.form_check import TEMPLATE, check_document, check_text, spec


def test_spec_comes_from_template():
    s = spec()
    assert s.labels == ("팀명", "회의명", "회의일시", "회의장소", "회의내용", "참석자 명단", "소속", "학번", "이름", "서명", "영수증", "사용 비용", "결제자")
    assert ("회의내용", "활동내용 자세하게 작성") in s.placeholders


def test_blank_template_matches_but_flags_unfilled():
    r = check_document(readers.classify(TEMPLATE.read_bytes(), TEMPLATE.name)[1])
    assert r.status == "match" and {k for k, _ in r.leftover} >= {"회의명", "회의내용", "작성자"}


def test_other_document_is_not_form():
    assert check_text("동아리 활동 계획서\n다음 학기 일정과 예산 계획을 정리했습니다. 팀명 테라바이트").status == "none"
    assert check_text("").status == "unknown"


def test_partial_lists_missing():
    r = check_text("팀명 회의명 회의일시 회의장소 회의내용 참석자 명단 소속 학번 이름 서명 영수증 그리고 아무거나 더 적은 글")
    assert r.status == "partial" and r.missing == ["사용 비용", "결제자"]


def test_garbled_pdf_text_goes_to_ocr():
    """한글 PDF의 글자 층이 깨져 나오면(한글이 거의 없음) 스캔본처럼 OCR로 읽는다."""
    from minutes_review.model import Document, Page

    from app.review.readers import garbled

    assert garbled(Document("pdf", "x.pdf", [Page(1, body="ÆÇÈ ±³¿À ÀÚ·á ¼­¸í ÆÀ¸í È¸ÀÇ¸í Âü¼®ÀÚ ¸í´Ü " * 3)]))
    assert not garbled(Document("pdf", "x.pdf", [Page(1, body="팀명 성장통 회의명 RAG 설계 회의일시 2026.10.27 참석자 명단")]))


def test_screen_rejects_keywords_without_form():
    """회의 관련 단어만으로 활동계획서·일반 회의록을 증빙 양식으로 받지 않는다."""
    import io

    from docx import Document as Docx

    from app.review.readers import screen

    def docx(text):
        buf = io.BytesIO()
        d = Docx()
        d.add_paragraph(text)
        d.save(buf)
        return buf.getvalue()

    assert "양식이 아닌" in screen([("a.docx", docx("10월 회의록입니다. 참석자 4명, 영수증 첨부"))])
    assert "양식이 아닌" in screen([("b.docx", docx("동아리 활동 계획서: 다음 학기 일정과 예산"))])


def test_writer_placeholder_only_is_needs_fix(monkeypatch):
    """작성자 이름만 '작성자명'으로 남으면 보완필요, 다른 칸 예시 글은 부적합 (2026-11-02)."""
    from app.review import form_check, pipeline

    def fake(leftover):
        return lambda doc, ocr=None: form_check.FormResult(status="match", ratio=1.0, missing=[], leftover=leftover)
    monkeypatch.setattr(form_check, "check_document", fake([("작성자", "작성자명")]))
    assert pipeline.form_check_item(None, None, None)["severity"] == "needs_fix"
    monkeypatch.setattr(form_check, "check_document", fake([("회의명", "회의 주제")]))
    assert pipeline.form_check_item(None, None, None)["severity"] == "reject"
