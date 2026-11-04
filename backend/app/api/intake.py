"""제출 접수: 메일 웹훅(운영)과 개발용 업로드.

웹훅: Cloudflare Email Worker가 `submit@jnuai-meetingfee.com`으로 온 메일 원본(raw MIME)을 그대로 POST한다.
      헤더 `X-Intake-Secret`로 확인하고, Message-ID로 중복을 막는다. 파싱은 여기(파이썬)서 한다.
"""
from __future__ import annotations

import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from sqlalchemy.orm import Session

from .. import worker
from ..config import get_settings
from ..db import get_db
from ..errors import ApiError
from ..models import KST, PROGRAMS, User
from ..schemas import ErrorResponse
from ..mail.intake import IntakeResult, intake_raw
from ..review import readers
from ..security import current_user


router = APIRouter(tags=["intake"])

@router.post("/intake/mail", response_model=IntakeResult, status_code=201, responses={401: {"model": ErrorResponse}},
             description="Cloudflare Email Worker 웹훅. 본문 = 메일 원본(raw MIME), 헤더 X-Intake-Secret")
async def intake_mail(request: Request, x_intake_secret: str = Header(""), db: Session = Depends(get_db)):
    secret = get_settings().intake_secret
    if not secret or not hmac.compare_digest(secret, x_intake_secret):
        raise ApiError(401, "UNAUTHORIZED", "웹훅 비밀 키가 맞지 않습니다.")
    return intake_raw(db, await request.body())


dev = APIRouter(prefix="/dev", tags=["dev"])


@dev.post("/intake", response_model=IntakeResult, status_code=201, responses={401: {"model": ErrorResponse}},
          description="(개발용) 메일 없이 파일을 올려 제출 건을 만든다. program을 비우면 서버가 정한다")
async def dev_intake(files: list[UploadFile] = File(default=[]), program: str | None = Form(None), mailbox: str | None = Form(None),
                     sender_name: str = Form("시험 학생"), sender_email: str = Form("student@jnu.ac.kr"),
                     subject: str = Form("[동아리] 회의비 증빙 제출합니다"), body: str = Form(""),
                     received_at: datetime | None = Form(None, description="접수 일시(R17). 비우면 지금"),
                     db: Session = Depends(get_db), user: User = Depends(current_user)):
    if program and program not in PROGRAMS:
        raise ApiError(422, "VALIDATION_ERROR", "프로그램 값이 올바르지 않습니다.")
    mailbox = mailbox or user.mailbox or ("wemeet_manager" if program in ("wemeet", "capstone") else "club_manager")
    data = [(f.filename or "첨부", await f.read()) for f in files]
    if why := readers.screen(data):
        return IntakeResult(skipped=why)
    if received_at and received_at.tzinfo:
        received_at = received_at.astimezone(KST).replace(tzinfo=None)
    sub = worker.create_submission(db, files=data, mailbox=mailbox, sender_name=sender_name, sender_email=sender_email, subject=subject,
                                   body_text=body, received_at=received_at, program=program)
    worker.enqueue(sub.id)
    return IntakeResult(id=sub.id)
