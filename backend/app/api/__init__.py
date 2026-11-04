"""API 라우터 모음. 경로는 docs/frontend-api.md 4장과 1:1."""
from fastapi import APIRouter

from ..config import get_settings
from . import auth, files, intake, programs, submissions, teams

router = APIRouter()


@router.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


router.include_router(auth.router)
router.include_router(programs.router)
router.include_router(submissions.router)
router.include_router(files.router)
router.include_router(teams.router)
router.include_router(intake.router)
if get_settings().dev_endpoints:
    router.include_router(intake.dev)
