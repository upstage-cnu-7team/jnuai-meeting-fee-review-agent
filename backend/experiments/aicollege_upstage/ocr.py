"""Upstage OCR(model=ocr) 호출, 파일 해시로 캐시."""
import hashlib, json, os, time
from pathlib import Path
import httpx

def ocr(path: Path, cache: Path) -> dict:
    data = path.read_bytes()
    key = cache / f"ocr-{hashlib.sha256(data).hexdigest()[:20]}.json"
    if key.exists():
        return json.loads(key.read_text())
    for attempt in range(3):
        r = httpx.post("https://api.upstage.ai/v1/document-digitization", headers={"Authorization": f"Bearer {os.environ['UPSTAGE_API_KEY']}"},
                       files={"document": (path.name, data)}, data={"model": "ocr"}, timeout=120)
        if r.status_code == 200:
            key.write_text(r.text)
            return r.json()
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"OCR 실패 {r.status_code}")
