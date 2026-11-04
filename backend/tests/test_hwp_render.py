"""HWP 미리보기: 머리말·꼬리말 로고(한국연구재단·한국판뉴딜·사업단)는 본문으로 끌어내리지 않고 쪽 위·아래에 원래 크기로 그린다.
(2026-11-02 VCCC·전자파: 로고가 쪽 너비로 커져 끝에 따로 쪽을 차지하던 문제)"""
from pathlib import Path

from app.review import hwp_render as h

WEMEET = Path(__file__).resolve().parents[1] / "forms/aicollege/별첨1-1_WE-Meet_회의비_지출증빙_양식(지출서류 묶음).hwp"


def test_header_footer_logos_stay_out_of_body():
    _, _, flow = h._parse(WEMEET.read_bytes())
    chromes = [x for x in flow if isinstance(x, h.Chrome)]
    assert chromes and all(len(c.head) == 2 and len(c.foot) == 1 for c in chromes)
    assert all(p.w and p.h for c in chromes for p in c.head + c.foot)  # 원래 크기
    assert not [x for x in flow if isinstance(x, (bytes, h.Pic))]  # 본문에 떠 있는 로고 없음



def test_first_page_not_blank():
    """첫 문단의 쪽 나눔 표시로 맨 앞에 빈 쪽이 생기지 않는다 (2026-11-02, 머리말 처리 뒤 생긴 회귀)."""
    import pypdfium2 as pdfium

    club = Path(__file__).resolve().parents[1] / "forms/aicollege/별첨1-1_회의비_지출증빙_양식.hwp"
    pdf = pdfium.PdfDocument(h.render_pdf(club.read_bytes()))
    assert pdf[0].get_textpage().get_text_range().strip()


def test_rotated_picture_is_turned_back():
    """한글에서 180° 돌려 놓은 그림은 바이트도 돌린다 (2026-11-02 AI-GO 영수증이 미리보기에서 거꾸로 보임)."""
    import io

    from PIL import Image as PILImage

    from minutes_review.extract.hwp import _rotated
    from minutes_review.model import Image

    im = PILImage.new("RGB", (20, 10), "white")
    im.putpixel((0, 0), (255, 0, 0))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    out = PILImage.open(io.BytesIO(_rotated(Image(data=buf.getvalue()), 180).data))
    assert out.size == (20, 10) and out.getpixel((19, 9))[0] > 200 and out.getpixel((0, 0)) == (255, 255, 255)
    out = PILImage.open(io.BytesIO(_rotated(Image(data=buf.getvalue()), 90).data))
    assert out.size == (10, 20)
