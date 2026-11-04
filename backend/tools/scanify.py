"""PDF를 스캔본처럼 바꾼다: 쪽을 이미지로 그린 뒤 회색조·살짝 기울임·노이즈·JPEG 압축을 거쳐 이미지 전용 PDF로 저장 (글자 층 없음).

    python tools/scanify.py <입력.pdf> <출력.pdf> [seed]
"""
import io
import random
import sys

import pypdfium2 as pdfium
from PIL import Image, ImageFilter


def scanify(data: bytes, seed: int = 0, dpi: int = 150) -> bytes:
    rnd = random.Random(seed)
    pages = []
    for page in pdfium.PdfDocument(data):
        im = page.render(scale=dpi / 72).to_pil().convert("L")
        im = im.rotate(rnd.uniform(-0.8, 0.8), expand=False, fillcolor=255, resample=Image.BICUBIC)
        px = im.load()
        w, h = im.size
        for _ in range(w * h // 400):  # 점 노이즈
            x, y = rnd.randrange(w), rnd.randrange(h)
            px[x, y] = rnd.choice((rnd.randint(150, 210), 255))
        im = im.filter(ImageFilter.GaussianBlur(0.5))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        pages.append(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
    out = io.BytesIO()
    pages[0].save(out, "PDF", save_all=True, append_images=pages[1:], resolution=dpi)
    return out.getvalue()


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    open(dst, "wb").write(scanify(open(src, "rb").read(), int(sys.argv[3]) if len(sys.argv) > 3 else 0))
