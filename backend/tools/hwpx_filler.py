"""HWPX 원본 양식(캡스톤 등)의 회의비 증빙 칸에 글자·그림을 채운다. 실험용 가상 회의록 생성.

- 캡스톤 지출 서류 묶음(HWPX)에서 회의비 증빙 구역(section)만 남겨 '학생이 회의비 양식만 떼어 보낸 파일'을 만든다.
- 칸 찾기: <hp:tc>의 <hp:cellAddr colAddr rowAddr>. 글자는 첫 문단 서식을 그대로 써서 줄마다 문단을 만든다.
- 그림: 원본 안의 그림 개체(<hp:pic>) 구조를 복사해 글자처럼 취급(treatAsChar)으로 넣고, BinData와 content.hpf에 등록한다.
값 배치는 tools/aicollege_samples.write_hwp 와 같다(표 0: 회의록, 표 1: 영수증).
"""
from __future__ import annotations

import copy
import io
import re
import sys
import zipfile
from pathlib import Path

from lxml import etree
from PIL import Image as PILImage

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.aicollege_samples import receipt_png, sign_cell, when  # noqa: E402

NS = {"hp": "http://www.hancom.co.kr/hwpml/2011/paragraph", "hc": "http://www.hancom.co.kr/hwpml/2011/core",
      "opf": "http://www.idpf.org/2007/opf/"}
HP = "{%s}" % NS["hp"]
MM = 7200 / 25.4


def _find_section(z: zipfile.ZipFile, word: str) -> str:
    matches = []
    for n in sorted(x for x in z.namelist() if re.fullmatch(r"Contents/section\d+\.xml", x)):
        root = etree.fromstring(z.read(n))
        # 안내 표에도 같은 양식명이 나온다. 표 안 인용 대신 본문 제목으로 찾는다.
        if any(word in "".join(p.itertext()) for p in root.findall("hp:p", NS)
               if p.find(".//hp:tbl", NS) is None):
            matches.append(n)
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(f"'{word}' 구역이 여러 개임: {matches}")
    raise ValueError(f"'{word}' 구역을 찾지 못함")


class HwpxFiller:
    def __init__(self, template: bytes, section_word: str = "회의비 지출 증빙", only_that_section: bool = True):
        self.z = zipfile.ZipFile(io.BytesIO(template))
        self.files = {n: self.z.read(n) for n in self.z.namelist()}
        self.sec = _find_section(self.z, section_word)
        self.only_that_section = only_that_section
        if only_that_section:  # 회의비 증빙 구역만 남긴다
            for n in [x for x in self.files if re.fullmatch(r"Contents/section\d+\.xml", x) and x != self.sec]:
                del self.files[n]
        self.root = etree.fromstring(self.files[self.sec])
        # 그림 개체 견본: 묶음 원본의 다른 구역에서 하나 가져온다
        pic_src = next((v for n, v in ((n, self.z.read(n)) for n in self.z.namelist() if n.startswith("Contents/section"))
                        if b"<hp:pic " in v), None)
        self.pic_tpl = etree.fromstring(pic_src).find(".//hp:pic", NS) if pic_src else None
        self.tables = self.root.findall(".//hp:tbl", NS)
        self.n_img = 0

    def _cell(self, table_no: int, col: int, row: int):
        for tc in self.tables[table_no].iter(HP + "tc"):
            a = tc.find("hp:cellAddr", NS)
            if int(a.get("colAddr")) == col and int(a.get("rowAddr")) == row:
                return tc
        raise KeyError((table_no, col, row))

    def _pic(self, png: bytes, w_mm: float):
        self.n_img += 1
        bid = f"fillimg{self.n_img}"
        self.files[f"BinData/{bid}.png"] = png
        im = PILImage.open(io.BytesIO(png))
        pw, ph = im.size
        w = int(w_mm * MM)
        h = int(w * ph / pw)
        org_w, org_h = pw * 75, ph * 75
        pic = copy.deepcopy(self.pic_tpl)
        pic.set("id", str(1900000000 + self.n_img))
        pic.set("instid", str(800000000 + self.n_img))
        for tag, attrs in (("orgSz", {"width": org_w, "height": org_h}), ("curSz", {"width": w, "height": h}),
                           ("sz", {"width": w, "height": h}), ("imgClip", {"left": 0, "top": 0, "right": org_w, "bottom": org_h}),
                           ("imgDim", {"dimwidth": org_w, "dimheight": org_h})):
            el = pic.find(f"hp:{tag}", NS)
            for k, v in attrs.items():
                el.set(k, str(v))
        pts = pic.find("hp:imgRect", NS)
        for i, (x, y) in enumerate(((0, 0), (org_w, 0), (org_w, org_h), (0, org_h))):
            p = pts.find(f"hc:pt{i}", NS)
            p.set("x", str(x))
            p.set("y", str(y))
        sca = pic.find("hp:renderingInfo/hc:scaMatrix", NS)
        sca.set("e1", f"{w / org_w:.6f}")
        sca.set("e5", f"{h / org_h:.6f}")
        pic.find("hc:img", NS).set("binaryItemIDRef", bid)
        pos = pic.find("hp:pos", NS)
        pos.set("treatAsChar", "1")
        rot = pic.find("hp:rotationInfo", NS)
        rot.set("centerX", str(w // 2))
        rot.set("centerY", str(h // 2))
        c = pic.find("hp:shapeComment", NS)
        if c is not None:
            c.text = "그림입니다."
        return pic, bid

    def fill(self, table_no: int, col: int, row: int, lines, images=()):
        lines = [lines] if isinstance(lines, str) else list(lines)
        tc = self._cell(table_no, col, row)
        sub = tc.find("hp:subList", NS)
        paras = sub.findall("hp:p", NS)
        first = paras[0]
        for p in paras[1:]:
            sub.remove(p)
        run0 = first.find("hp:run", NS)
        char = run0.get("charPrIDRef") if run0 is not None else "0"
        for el in list(first):
            first.remove(el)
        out = []
        for i, text in enumerate(lines or [""]):
            p = first if i == 0 else copy.deepcopy(first)
            for el in list(p):
                p.remove(el)
            run = etree.SubElement(p, HP + "run", charPrIDRef=char)
            if i == 0:
                for png, w_mm in images:
                    pic, _ = self._pic(png, w_mm)
                    run.append(pic)
            t = etree.SubElement(run, HP + "t")
            t.text = text
            if i:
                sub.append(p)
            out.append(p)

    def build(self) -> bytes:
        self.files[self.sec] = etree.tostring(self.root, xml_declaration=True, encoding="UTF-8", standalone=True)
        hpf = self.files["Contents/content.hpf"].decode("utf-8")
        kept = {n.split("/")[-1].removesuffix(".xml") for n in self.files if n.startswith("Contents/section")}
        hpf = re.sub(r'<opf:item id="(section\d+)"[^>]*/>', lambda m: m[0] if m[1] in kept else "", hpf)
        hpf = re.sub(r'<opf:itemref idref="(section\d+)"[^>]*/>', lambda m: m[0] if m[1] in kept else "", hpf)
        if self.only_that_section:
            # 한컴은 첫 본문 파일 section0.xml을 요구한다. 로컬 리더는 section1만 있어도 읽는다.
            old = self.sec.rsplit("/", 1)[-1].removesuffix(".xml")
            hpf = hpf.replace(f'id="{old}"', 'id="section0"').replace(f'idref="{old}"', 'idref="section0"')
            hpf = hpf.replace(f'href="{self.sec}"', 'href="Contents/section0.xml"')
        items = "".join(f'<opf:item id="fillimg{i}" href="BinData/fillimg{i}.png" media-type="image/png" isEmbeded="1"/>'
                        for i in range(1, self.n_img + 1))
        hpf = hpf.replace("</opf:manifest>", items + "</opf:manifest>")
        self.files["Contents/content.hpf"] = hpf.encode("utf-8")
        header = etree.fromstring(self.files["Contents/header.xml"])
        header.set("secCnt", str(len(kept)))
        self.files["Contents/header.xml"] = etree.tostring(header, xml_declaration=True, encoding="UTF-8", standalone=True)
        for n in ("Preview/PrvText.txt", "Preview/PrvImage.png"):  # 원본 미리보기는 빈 양식이라 뺀다
            self.files.pop(n, None)
        out = io.BytesIO()
        files = dict(self.files)
        if self.only_that_section:
            files["Contents/section0.xml"] = files.pop(self.sec)
        with zipfile.ZipFile(out, "w") as z:
            z.writestr(zipfile.ZipInfo("mimetype", (2026, 1, 1, 0, 0, 0)), self.files["mimetype"], zipfile.ZIP_STORED)
            for n, b in files.items():
                if n != "mimetype":
                    z.writestr(zipfile.ZipInfo(n, (2026, 1, 1, 0, 0, 0)), b, zipfile.ZIP_DEFLATED)
        return out.getvalue()


def write_hwpx(c: dict, template: bytes) -> bytes:
    """tools/aicollege_samples.write_hwp 와 같은 칸 배치로 HWPX 양식을 채운다."""
    f = HwpxFiller(template)
    f.fill(0, 1, 1, c["team"])
    f.fill(0, 1, 2, c["title"])
    f.fill(0, 1, 3, when(c))
    f.fill(0, 5, 3, c["place"])
    f.fill(0, 1, 4, c["content"])
    for k, (aff, sid, name, signed) in enumerate(c["attendees"]):
        row = 6 + k
        f.fill(0, 1, row, aff)
        f.fill(0, 2, row, sid)
        f.fill(0, 4, row, name)
        f.fill(0, 6, row, *sign_cell(signed, name, k))
    for row in range(6 + len(c["attendees"]), 8):
        f.fill(0, 6, row, "")
    d = c["date"]
    f.fill(0, 0, 12, f"2026년 {d.month}월 {d.day}일    작성자 : {c['writer']} ( 인 )")
    if c["receipt"] is None:
        f.fill(1, 0, 1, ["영수증 첨부란", "(연구비카드 매출전표)"])
    else:
        f.fill(1, 0, 1, [""], [(receipt_png(c["receipt"]), 60)])
    f.fill(1, 1, 2, f"{c['amount']} 원")
    aff, name, signed = c["payer"]
    f.fill(1, 1, 4, aff)
    f.fill(1, 2, 4, name)
    f.fill(1, 3, 4, *sign_cell(signed, name, 9))
    return f.build()
