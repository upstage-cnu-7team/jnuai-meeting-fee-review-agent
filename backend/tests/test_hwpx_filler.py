"""캡스톤 묶음에서 안내문 대신 실제 회의록을 채우는 회귀 시험."""
import io
import zipfile
from pathlib import Path

import pytest
from lxml import etree

from app.review import readers
from app.review.form_check import check_document
from tools.aicollege_samples import BASE, case, when
from tools.hwpx_filler import HwpxFiller, NS, write_hwpx

TEMPLATE = next((Path(__file__).parents[1] / "forms/aicollege").glob("*캡스톤*.hwpx"))


def test_datetime_fill_preserves_place_cell():
    f = HwpxFiller(TEMPLATE.read_bytes())
    assert f.sec == "Contents/section1.xml"
    place = etree.tostring(f._cell(0, 5, 3))
    f.fill(0, 1, 3, when(BASE))
    assert etree.tostring(f._cell(0, 5, 3)) == place
    f.fill(0, 5, 3, BASE["place"])


@pytest.mark.parametrize("changes", [{}, {"receipt": None, "payer": ("인공지능학부", "김가온", False)},
                                      {"attendees": BASE["attendees"][:3] + [("가상학과", "202400004", "최라온", "typed")]}])
def test_filled_capstone_roundtrip(changes):
    c = case("test", "가상 회의록", **changes)
    data = write_hwpx(c, TEMPLATE.read_bytes())
    fmt, doc = readers.classify(data, "capstone.hwpx")
    assert fmt == "hwpx" and doc is not None
    assert len(doc.pages) == 1 and len(doc.pages[0].tables) == 2
    assert readers.form_fields(doc) == {"team_name": c["team"], "meeting_title": c["title"],
                                        "place": c["place"], "used_amount": 60000}
    assert when(c) in readers.full_text(doc)
    assert doc.pages[0].tables[0].rows[4][1].text == "\n".join(c["content"])
    form = check_document(doc)
    assert form.status == "match" and not form.leftover
    marks = readers.local_marks(doc)
    assert marks["attendee_signed"] == {a[2]: a[3] for a in c["attendees"]}
    assert marks["payer_signed"] == c["payer"][2]
    assert marks["receipt_image"] == (c["receipt"] is not None)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.testzip() is None
        sections = [n for n in z.namelist() if n.startswith("Contents/section")]
        assert sections == ["Contents/section0.xml"]
        assert etree.fromstring(z.read("Contents/header.xml")).get("secCnt") == "1"
        hpf = etree.fromstring(z.read("Contents/content.hpf"))
        assert hpf.xpath("//opf:itemref[starts-with(@idref, 'section')]/@idref", namespaces=NS) == ["section0"]
        for item in hpf.findall("opf:manifest/opf:item", NS):
            assert item.get("href") in z.namelist()
        for page in doc.pages:
            for table in page.tables:
                for row in table.rows:
                    for cell in row:
                        assert all(image.data.startswith(b"\x89PNG") for image in cell.images)


def test_full_bundle_preserves_other_sections():
    f = HwpxFiller(TEMPLATE.read_bytes(), only_that_section=False)
    f.fill(0, 5, 3, BASE["place"])
    with zipfile.ZipFile(io.BytesIO(f.build())) as filled, zipfile.ZipFile(TEMPLATE) as original:
        for n in ("Contents/section0.xml", "Contents/section2.xml", "Contents/section3.xml"):
            assert filled.read(n) == original.read(n)
        assert etree.fromstring(filled.read("Contents/header.xml")).get("secCnt") == "4"
