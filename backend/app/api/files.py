"""쪽 이미지·원본 다운로드. 서명 URL(exp·sig)로 확인하므로 로그인 헤더가 필요 없다(<img src>에 바로 넣기)."""
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..models import File
from ..schemas import ErrorResponse
from ..security import check_signed
from ..storage import original_path, page_path

router = APIRouter(prefix="/files", tags=["files"])
ERR = {403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}}
MIME = {"pdf": "application/pdf", "scan": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "hwp": "application/x-hwp", "hwpx": "application/hwp+zip"}


@router.get("/{file_id}/pages/{n}.png", response_class=Response, responses={**ERR, 200: {"content": {"image/png": {}}}})
def page_image(file_id: str, n: int, exp: int = Query(...), sig: str = Query(...), db: Session = Depends(get_db)):
    check_signed(f"/api/files/{file_id}/pages/{n}.png", exp, sig)
    p = page_path(file_id, n)
    if db.get(File, file_id) is None or not p.exists():
        raise ApiError(404, "FILE_NOT_FOUND", "미리보기를 찾을 수 없습니다.")
    return FileResponse(p, media_type="image/png", headers={"Cache-Control": "private, max-age=1800"})


@router.get("/{file_id}/download", response_class=Response, responses=ERR)
def download(file_id: str, exp: int = Query(...), sig: str = Query(...), db: Session = Depends(get_db)):
    check_signed(f"/api/files/{file_id}/download", exp, sig)
    f = db.get(File, file_id)
    if f is None or not original_path(f.sha256).exists():
        raise ApiError(404, "FILE_NOT_FOUND", "파일을 찾을 수 없습니다.")
    return FileResponse(original_path(f.sha256), media_type=MIME.get(f.format, "application/octet-stream"),
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(f.name)}"})
