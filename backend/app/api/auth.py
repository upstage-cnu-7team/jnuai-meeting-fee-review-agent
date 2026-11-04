from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import ApiError
from ..models import User
from ..schemas import ErrorResponse, LoginRequest, LoginResponse, UserOut
from ..security import current_user, make_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(u: User) -> dict:
    return {"name": u.name, "role": u.role, "programs": u.programs}


@router.post("/login", response_model=LoginResponse, responses={401: {"model": ErrorResponse}})
def login(body: LoginRequest, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == body.username))
    if u is None or not verify_password(body.password, u.password_hash):
        raise ApiError(401, "INVALID_CREDENTIALS", "아이디 또는 비밀번호가 맞지 않습니다.")
    return {"access_token": make_token(u), "user": user_out(u)}


@router.get("/me", response_model=UserOut, responses={401: {"model": ErrorResponse}})
def me(user: User = Depends(current_user)):
    return user_out(user)
