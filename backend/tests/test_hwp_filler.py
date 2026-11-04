"""WE-Meet 작성자 칸을 짧게 채울 때 남는 서식 위치 회귀 시험."""
import struct
from pathlib import Path

from tools.aicollege_samples import BASE, HwpFiller, write_hwp


def test_wemeet_shortened_paragraph_keeps_style_offsets_in_bounds():
    template = next((Path(__file__).parents[1] / "forms/aicollege").glob("*WE-Meet*.hwp"))
    f = HwpFiller(write_hwp(BASE, template.read_bytes()))
    # 원래 작성자 칸은 글자 위치 0, 6, 62, 72에 서식이 있지만 새 글은 41자다.
    ph = f.cells(0)[(0, 12)][0]
    head = f.recs[ph][2]
    size = struct.unpack_from("<I", head)[0] & 0x7fffffff
    for tag, level, body in f.recs[ph + 1:]:
        if level <= f.recs[ph][1]:
            break
        if tag in (68, 69):
            stride, offset = (8, 12) if tag == 68 else (36, 16)
            assert struct.unpack_from("<H", head, offset)[0] == len(body) // stride
            assert all(struct.unpack_from("<I", body, i)[0] < size for i in range(0, len(body), stride))
    assert {n for n in f.streams if n.startswith("BodyText/")} == {
        "BodyText/Section0", "BodyText/Section1", "BodyText/Section2"}
