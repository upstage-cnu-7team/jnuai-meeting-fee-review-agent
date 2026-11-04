"""모든 4xx/5xx를 `{"error": {"code", "message"}}` 형식으로 (frontend-api.md 4장 공통)."""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def not_found(what: str = "SUBMISSION") -> ApiError:
    msg = {"SUBMISSION": "제출 건을 찾을 수 없습니다.", "TEAM": "팀을 찾을 수 없습니다.", "FILE": "파일을 찾을 수 없습니다.",
           "CHECK": "조건을 찾을 수 없습니다.", "RULE_SET": "기준을 찾을 수 없습니다."}.get(what, "찾을 수 없습니다.")
    return ApiError(404, f"{what}_NOT_FOUND", msg)


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install(app: FastAPI):
    @app.exception_handler(ApiError)
    async def _api(_: Request, e: ApiError):
        return JSONResponse(_body(e.code, e.message), status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _valid(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        return JSONResponse(_body("VALIDATION_ERROR", f"요청 값이 올바르지 않습니다: {where}"), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR")
        msg = e.detail if isinstance(e.detail, str) and e.detail not in ("Not Found", "Method Not Allowed") else {
            404: "찾을 수 없습니다.", 405: "허용되지 않는 요청입니다."}.get(e.status_code, "요청을 처리할 수 없습니다.")
        return JSONResponse(_body(code, msg), status_code=e.status_code)

    @app.exception_handler(Exception)
    async def _any(_: Request, e: Exception):  # 원문(개인정보)이 섞일 수 있어 메시지에 예외 내용을 넣지 않는다
        return JSONResponse(_body("INTERNAL_ERROR", "서버 오류가 발생했습니다."), status_code=500)
