"""사업단 회의비 양식 접수와 안내문·다른 신청서 거르기."""
import io
from pathlib import Path

import pytest
from docx import Document as Docx

from app.review import readers
from minutes_review.model import Cell, Document, Page, Table

FORMS = Path(__file__).parents[1] / "forms/aicollege"


@pytest.mark.parametrize("pattern", ["별첨1-1_회의비*.hwp", "*WE-Meet*.hwp", "*캡스톤*.hwpx"])
def test_official_forms_are_received_even_when_blank(pattern):
    p = next(FORMS.glob(pattern))
    assert readers.screen([("renamed" + p.suffix, p.read_bytes())]) is None


def test_original_club_guide_is_not_a_submission():
    p = FORMS / "별첨1_회의비_참고사항.hwp"
    assert readers.screen([(p.name, p.read_bytes())]) is not None


def test_guidance_listing_all_labels_is_not_a_form():
    text = "팀명 회의명 회의일시 회의장소 회의내용 참석자 명단 소속 학번 이름 서명 영수증 사용 비용 결제자"
    doc = Document("docx", "guide.docx", [Page(1, body="회의비 지출 증빙 작성 안내\n" + text)])
    assert not readers.is_minutes(doc, "docx")


def test_form_without_title_is_received_from_cell_structure():
    labels = ["팀명", "회의명", "회의일시", "회의장소", "회의내용", "소속", "학번", "이름", "서명", "영수증", "결제자"]
    doc = Document("docx", "minutes.docx", [Page(1, tables=[Table([[Cell(k), Cell("가상 값")] for k in labels])])])
    assert readers.is_minutes(doc, "docx")


def test_filename_and_meeting_keywords_do_not_override_contents():
    d, out = Docx(), io.BytesIO()
    d.add_paragraph("도서 구매 요청서: 회의에서 선정한 교재 구매. 참석자 이름 및 영수증은 추후 제출")
    d.save(out)
    assert readers.screen([("회의비_지출증빙.docx", out.getvalue())]) is not None
    p = FORMS / "별첨1-1_회의비_지출증빙_양식.hwp"
    assert readers.screen([("회의비_지출증빙.docx", out.getvalue()), ("minutes.hwp", p.read_bytes())]) is None


def test_scan_and_no_attachment_are_not_claimed_to_be_verified_forms():
    # 스캔은 OCR 전 보류 후보이며 첨부 없는 메일은 기존 미첨부 보완 흐름으로 받는다.
    assert readers.screen([]) is None
    assert readers.is_minutes(None, "scan")
    assert not readers.is_minutes(None, "hwp")
