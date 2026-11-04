"""설정: backend/.env 또는 환경변수에서 읽는다. 비밀값은 코드·커밋에 넣지 않는다."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND / ".env", extra="ignore")

    upstage_api_key: str = ""
    database_url: str = f"sqlite:///{BACKEND / 'data' / 'app.db'}"
    data_dir: Path = BACKEND / "data"

    # 로그인 토큰·서명 URL 비밀키. 운영에서는 반드시 .env로 바꾼다.
    secret_key: str = "dev-secret-change-me"
    token_hours: int = 12
    signed_url_minutes: int = 30

    # 첫 실행 때 만드는 계정의 초기 비밀번호 (.env). 비어 있으면 그 계정은 만들지 않는다.
    seed_password_club: str = ""
    seed_password_wemeet: str = ""
    seed_password_admin: str = ""

    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    dev_endpoints: bool = True  # /api/dev/* (운영에서는 끈다)

    # 메일 수집 웹훅 비밀 키 (Cloudflare Email Worker가 헤더로 보냄)
    intake_secret: str = ""
    # 이 시각(한국 시간) 이전에 받은 메일은 접수하지 않는다. 예: 2026-10-30T12:30
    intake_since: datetime | None = None
    intake_review_mode: bool = False  # 재전송 정확도 검토 중에는 비양식·중복도 원본 보존
    # 원래 받은 담당자 주소 → 메일함: "club_manager=주소,wemeet_manager=주소"
    manager_mailboxes: str = ""
    # Gmail 임시 수집 (Cloudflare → Gmail 전달분). 앱 비밀번호는 사용자가 .env에 직접 넣는다
    gmail_address: str = ""
    gmail_app_password: str = ""
    gmail_poll_minutes: int = 0  # 0이면 서버가 스스로 가져오지 않음

    # 회신 "웹메일에서 열기"용 OWA 주소
    owa_base: str = "https://email.jnu.ac.kr/owa/"
    compose_max_chars: int = 200  # 주소에 넣을 본문 최대 글자 수 (한글 기준)

    # 판정 모델
    solar_model: str = "solar-pro4"
    ie_model: str = "information-extract"
    run_review_inline: bool = False  # 테스트용: 백그라운드 대신 요청 안에서 바로 검수

    # 대용량 제출: 이 크기를 넘는 파일은 안의 사진을 줄인 사본을 Upstage에 보낸다 (app/review/slim.py)
    slim_upload_bytes: int = 10_000_000
    image_max_px: int = 2000  # 줄일 때 사진 긴 변 (영수증 글자가 읽히는 크기)
    slim_image_min_bytes: int = 500_000  # 이보다 작은 그림(서명 등)은 건드리지 않는다

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"


@lru_cache
def get_settings() -> Settings:
    return Settings()
