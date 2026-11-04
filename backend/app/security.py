"""비밀번호 해시(argon2), 로그인 토큰(JWT), 쪽 이미지·다운로드용 서명 URL, 권한 확인."""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .errors import ApiError
from .models import Submission, User

_ph = PasswordHasher()
_bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def make_token(user: User) -> str:
    s = get_settings()
    exp = datetime.now(timezone.utc) + timedelta(hours=s.token_hours)
    return jwt.encode({"sub": user.id, "exp": exp}, s.secret_key, algorithm="HS256")


def current_user(cred: HTTPAuthorizationCredentials | None = Depends(_bearer), db: Session = Depends(get_db)) -> User:
    if cred is None:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다.")
    try:
        sub = jwt.decode(cred.credentials, get_settings().secret_key, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 만료되었습니다. 다시 로그인해 주세요.")
    user = db.get(User, sub)
    if user is None:
        raise ApiError(401, "UNAUTHORIZED", "로그인이 필요합니다.")
    return user


def require_program(user: User, program: str):
    if program not in user.programs:
        raise ApiError(403, "FORBIDDEN", "이 프로그램을 볼 권한이 없습니다.")


def can_see(user: User, sub: Submission) -> bool:
    """담당자는 자기 메일함 제출만 본다. 프로그램이 정해졌으면 맡은 프로그램인지, 미확정이면 메일함이 같은지 본다."""
    if user.role == "admin":
        return True
    if sub.program is not None:
        return sub.program in user.programs
    return sub.mailbox == user.mailbox


def require_submission(user: User, sub: Submission | None) -> Submission:
    from .errors import not_found

    if sub is None:
        raise not_found("SUBMISSION")
    if not can_see(user, sub):
        raise ApiError(403, "FORBIDDEN", "이 제출 건을 볼 권한이 없습니다.")
    return sub


# ---- 서명 URL: <img src>에 그대로 넣을 수 있게 로그인 헤더 없이 exp·sig로 확인 ----

def _sig(path: str, exp: int) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"{path}|{exp}".encode(), hashlib.sha256).hexdigest()[:32]


def signed_url(path: str) -> str:
    exp = int(time.time()) + get_settings().signed_url_minutes * 60
    return f"{path}?exp={exp}&sig={_sig(path, exp)}"


def check_signed(path: str, exp: int, sig: str):
    if exp < time.time() or not hmac.compare_digest(_sig(path, exp), sig):
        raise ApiError(403, "URL_EXPIRED", "주소가 만료되었습니다. 화면을 새로고침해 주세요.")
