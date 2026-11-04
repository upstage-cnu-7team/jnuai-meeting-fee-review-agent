"""API 요청·응답 모델. docs/frontend-api.md 8장 TypeScript 타입과 1:1로 맞춘다 (바뀌면 문서를 먼저 고친다)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Program = Literal["club", "aim", "hackathon", "wemeet", "capstone"]
ProcessingStatus = Literal["queued", "processing", "done", "failed"]
Verdict = Literal["pass", "needs_fix", "reject", "review"]
ReviewStatus = Literal["pending", "confirmed"]
ReplyStatus = Literal["none", "draft", "sending", "sent", "failed", "not_needed"]
CheckResult = Literal["met", "unmet", "review", "excluded"]
CheckBy = Literal["code", "ai", "extract+code"]


class ErrorBody(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---- 인증 ----

class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    name: str
    role: Literal["manager", "admin"]
    programs: list[Program]


class LoginResponse(BaseModel):
    access_token: str
    user: UserOut


# ---- 목록 ----

class Summary(BaseModel):
    today_received: int
    unconfirmed: int
    ai_review: int
    needs_fix: int
    reject: int
    reply_failed: int
    processing: int


class TeamListItem(BaseModel):
    id: str | None = Field(description="'팀 미확정' 항목은 null. 목록 조회 때 team_id=unassigned")
    name: str
    unconfirmed: int
    total: int
    last_received_at: str | None


class TeamRef(BaseModel):
    id: str | None
    name: str


class Sender(BaseModel):
    name: str
    email: str


class ListSummary(BaseModel):
    meeting_date: str | None
    total_amount: int | None
    attendee_count: int | None
    failed_checks: list[str]
    review_checks: list[str]
    failed_count: int
    review_count: int


class SubmissionListItem(BaseModel):
    id: str
    program: Program | None
    team: TeamRef
    received_at: str
    sender: Sender
    subject: str
    processing_status: ProcessingStatus
    verdict: Verdict | None
    review_status: ReviewStatus
    reply_status: ReplyStatus
    summary: ListSummary | None


class SubmissionPage(BaseModel):
    items: list[SubmissionListItem]
    total: int
    page: int
    size: int


# ---- 상세 ----

class TeamDetailRef(TeamRef):
    match: Literal["auto", "manual", "none"]
    match_reason: str | None


class MailOut(BaseModel):
    subject: str
    body_text: str


class PageImage(BaseModel):
    n: int
    url: str = Field(description="서명 URL. <img src>에 그대로 넣는다. 30분 뒤 만료")
    width: int
    height: int


class Attachment(BaseModel):
    file_id: str
    name: str
    kind: Literal["minutes", "receipt", "other"]
    format: str
    page_count: int
    size: int
    pages: list[PageImage]
    download_url: str


class RuleSetRef(BaseModel):
    id: str
    version: int
    confirmed_at: str | None


class Alternative(BaseModel):
    label: str = Field(description="예: '식비로 보면'")
    result: Literal["met", "unmet"]
    detail: str
    expected: str | None = None


class Evidence(BaseModel):
    field: str | None
    found: str | None
    expected: str | None
    file_id: str | None
    page: int | None
    bbox: list[float] | None = Field(None, description="쪽 이미지 기준 0~1 비율 [x0, y0, x1, y1]")
    rule_source: str | None
    alternatives: list[Alternative] | None = Field(None, description="애매한 구분을 두 방식으로 모두 계산한 결과. 엇갈리면 result=review")


class CheckOut(BaseModel):
    check_id: str
    name: str
    by: CheckBy
    severity: Literal["reject", "needs_fix"]
    result: CheckResult
    ai_result: CheckResult
    overridden: bool
    message: str
    evidence: Evidence
    manager_note: str | None


class ReplyOut(BaseModel):
    status: ReplyStatus
    to: str
    subject: str
    body: str
    internal_notes: list[str]
    edited_by_manager: bool
    sent_at: str | None
    error: str | None
    compose_url: str | None = Field(None, description="담당자 웹메일(OWA) 새 메일 창 주소 (잠정)")
    compose_truncated: bool = Field(False, description="본문이 길어 주소에 다 못 넣음 → [초안 복사]")


class PrevSubmission(BaseModel):
    id: str
    received_at: str
    verdict: Verdict | None
    reply_status: ReplyStatus


class SubmissionDetail(BaseModel):
    id: str
    program: Program | None
    team: TeamDetailRef
    received_at: str
    sender: Sender
    mail: MailOut
    attachments: list[Attachment]
    processing_status: ProcessingStatus
    processing_error: str | None
    verdict: Verdict | None
    review_status: ReviewStatus
    reply_status: ReplyStatus
    updated_at: str
    rule_set: RuleSetRef | None
    extracted: dict | None = Field(description="추출 요약. 학번·카드번호는 마스킹됨")
    checks: list[CheckOut]
    reply: ReplyOut
    previous_submissions: list[PrevSubmission]


# ---- 수정 요청 ----

class CheckPatch(BaseModel):
    result: Literal["met", "unmet"] | None = Field(description="null이면 AI 결과로 되돌림")
    note: str | None = None


class CheckPatchResponse(BaseModel):
    verdict: Verdict | None
    check: CheckOut
    reply: ReplyOut
    reply_regenerated: bool
    updated_at: str


class ReplyPut(BaseModel):
    subject: str
    body: str


class ConfirmRequest(BaseModel):
    reply: Literal["not_needed"] | None = "not_needed"


class StatusResponse(BaseModel):
    review_status: ReviewStatus
    reply_status: ReplyStatus


class SubmissionPatch(BaseModel):
    team_id: str | None = None
    program: Program | None = None
    review_status: Literal["pending"] | None = None


class QueuedResponse(BaseModel):
    processing_status: Literal["queued"]


class SendResponse(BaseModel):
    status: Literal["sending"]


# ---- 팀·기준 ----

class TeamSubmission(BaseModel):
    id: str
    received_at: str
    meeting_date: str | None
    total_amount: int | None
    verdict: Verdict | None
    reply_status: ReplyStatus


class TeamDetail(BaseModel):
    id: str
    program: Program
    name: str
    aliases: list[str]
    known_senders: list[str]
    submissions: list[TeamSubmission]


class AliasesPut(BaseModel):
    aliases: list[str]


class Condition(BaseModel):
    id: str
    name: str
    by: CheckBy | None = None
    severity: Literal["reject", "needs_fix"] | None = None
    params: dict | None = None
    source: str | None = None
    enabled: bool
    excluded_reason: str | None = None


class RuleSetOut(BaseModel):
    id: str
    program: Program
    version: int
    status: Literal["draft", "confirmed"]
    confirmed_by: str | None
    confirmed_at: str | None
    conditions: list[Condition]
    note: str | None = Field(None, description="이 프로그램 기준이 없어 다른 프로그램 기준을 임시로 쓰는 경우 안내")
