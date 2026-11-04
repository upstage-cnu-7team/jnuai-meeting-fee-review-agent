# 백엔드 계획 — FastAPI · LangGraph · SQLite · Upstage

- 작성: 2026-10-28
- 기준 문서: `docs/frontend-api.md`(API 약속), `backend/experiments/aicollege_upstage/README.md`(실험 결과)
- 이 문서는 **처음부터 다시 짜는 백엔드의 설계와 작업 순서**다. 새 Claude Code 세션은 이 문서의 "작업 순서"에서 다음 단계를 골라 시작한다.

---

## 1. 전체 구조

```
[메일 수집]                                 [담당자 화면 (frontend)]
Power Automate ─▶ 우리 메일함                       │ HTTP
        │ (미검증: 서버가 읽기)                     ▼
        ▼                               ┌──────── FastAPI (app/api) ────────┐
  intake (메일 → 제출 건 저장) ─────────▶│  submissions / teams / rules / auth │
  개발 중엔 업로드 API로 대체            └──────────────┬────────────────────┘
                                                      │ 대기열(백그라운드 작업)
                                                      ▼
                                  LangGraph 검수 그래프 (app/graph)
                                  read → extract → (scan?) → judge → draft
                                                      │
                                       Upstage API ◀──┘   SQLite(app.db) ◀─ 결과 저장
                                                      │
[전송] ─▶ reply_status=sending ─▶ 메일 브리지 ─▶ 담당자 Power Automate ─▶ 학생에게 회신
```

## 2. 목표 폴더 구조

```
backend/
  app/
    main.py              FastAPI 앱, CORS, 라우터 등록
    config.py            설정 (pydantic-settings: UPSTAGE_API_KEY, DATABASE_URL, …)
    db.py                SQLAlchemy 엔진·세션
    models.py            테이블 (아래 4절)
    schemas.py           API 응답 모델 (frontend-api.md와 1:1)
    api/
      auth.py  programs.py  submissions.py  files.py  teams.py  rules.py  dev.py
    review/              ★ 판정 로직 (프레임워크 독립, 순수 함수)
      readers.py         minutes_review.extract 감싸기 (형식 판별, 칸 안 그림)
      upstage.py         Information Extract · Solar · OCR 클라이언트 + 해시 캐시 + 초당 1건
      signature.py       스캔 서명 판정 (experiments/…/scan_signature.py 이식)
      conditions.py      조건 유형별 판정 함수 (R01~R17)
      verdict.py         항목 결과 → 종합 판정
      draft.py           회신 초안 (미충족만, 확인필요는 담당자 메모)
      team_match.py      양식 제목·담당자 메일함·메일 단어 → 프로그램, 별칭 대조 → 팀 (rules/teams.yaml)
    graph/
      review_graph.py    LangGraph: 노드는 review/ 함수 호출만
    worker.py            대기열 처리 (처음엔 FastAPI BackgroundTasks, 필요하면 별도 프로세스)
    mail/
      bridge.py          수집함 읽기 · 발송요청 메일 보내기 (인터페이스만 먼저)
  rules/aicollege_club.yaml   seed
  tests/
```

`experiments/`와 `minutes_review/`는 **참고·이식 원본**이다. 이식이 끝나면 `app/review`가 정본이 된다. 실험 테스트(72/72)를 `tests/`로 옮겨 회귀 시험으로 쓴다.

## 3. 검수 파이프라인 (LangGraph)

```
START → load_files → classify_format ─┬─ digital ─▶ read_local (칸 안 그림·글자)
                                       └─ scan ────▶ ocr_signature (OCR 좌표 + 잉크)
      → extract (Upstage IE, 캐시) → judge_code → judge_solar → combine
      → draft_reply → END
```

| 노드 | 하는 일 | 실험 원본 |
|---|---|---|
| load_files | 첨부 바이트·파일명 로드, 회의록/영수증/기타 분류 | `minutes_review/extract/__init__.py` |
| classify_format | hwp/hwpx/docx/pdf(글자층 있음)/scan(이미지만)/image | `minutes_review/extract` sniff |
| read_local | 서명 칸·영수증 칸 그림 여부, 쪽 이미지 생성 | `minutes_review/extract/*` |
| ocr_signature | 스캔본 서명 칸 판정 | `scan_signature.py` |
| extract | Information Extract 23필드 | `run_cases.py: extract()`, `schema.json` |
| judge_code | 계산형 조건 | `run_cases.py` 판정부 |
| judge_solar | 장소·주류·내용·식비/다과비 | `run_cases.py: SOLAR_SYS` |
| combine | 종합 판정 (`reject` > `needs_fix` > `review` > `pass`) | |
| draft_reply | 회신 초안 + internal_notes | `minutes_review/draft.py` |

- 상태(State): `submission_id`, `files`, `format`, `local`, `extracted`, `checks`, `verdict`, `reply`, `errors`
- 체크포인터: SQLite (`langgraph-checkpoint-sqlite`). 실패한 노드부터 재시도한다.
- 담당자 확인 대기는 그래프 밖(DB `review_status`)에서 관리한다. 그래프는 초안까지 만들고 끝난다. interrupt는 필요해지면 넣는다.
- Upstage 실패나 시간 초과는 3회 재시도한다. 그래도 실패하면 `processing_status=failed`로 두고 원본은 보여 준다.

## 4. DB 테이블 (SQLite, SQLAlchemy)

| 테이블 | 주요 컬럼 |
|---|---|
| `users` | id, username, password_hash, name, role(manager/admin), programs(JSON), mailbox(club_manager/wemeet_manager). 계정 2개: 동아리 담당자 `[club, aim, hackathon]`, 위밋 담당자 `[wemeet, capstone]` |
| `teams` | id, program(club/aim/hackathon/wemeet/capstone), name, aliases(JSON), known_senders(JSON). 같은 이름도 프로그램이 다르면 다른 행 |
| `rule_sets` | id, program, version, status(draft/confirmed), conditions(JSON), confirmed_by, confirmed_at |
| `submissions` | id, program(null = 미확정), mailbox(어느 담당자 메일함으로 왔나: 수집 메일의 TO로 결정), team_id(null=미확정), team_match(auto/manual/none), mail_message_id(UNIQUE, 중복 방지), sender_name, sender_email, subject, body_text, received_at, processing_status, processing_error, verdict, review_status, rule_set_id, model_info(JSON), extracted(JSON), created_at |
| `files` | id, submission_id, name, kind(minutes/receipt/other), format, size, sha256, path, page_count |
| `checks` | id, submission_id, check_id(R01…), name, by, severity, result, ai_result, overridden, message, evidence(JSON), manager_note |
| `replies` | submission_id(PK), status, to_email, subject, body, internal_notes(JSON), edited_by_manager, sent_at, error |
| `upstage_cache` | key(sha256+schema), kind(ie/ocr/solar), response(JSON), created_at |

- 원본 파일은 DB가 아니라 `backend/data/files/<sha256>`에 둔다. 쪽 이미지는 `backend/data/pages/<file_id>/<n>.png`에 둔다.
- `rule_sets`는 앱 시작 시 비어 있으면 `rules/aicollege_club.yaml`로 seed한다(v1, confirmed).
- 시간은 모두 Asia/Seoul 기준 ISO 8601로 저장한다.

## 5. API ↔ 구현 매핑

API 명세는 `docs/frontend-api.md`가 정본이다. 우선순위도 거기를 따른다(P0 → P1 → P2).

추가로 **개발용** 엔드포인트를 둔다. 메일 연동 전까지 쓰고, 운영에서는 끈다.

| 메서드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/dev/intake` | multipart: program, sender_email, subject, body, files[] → 제출 건 생성 + 검수 대기열 |
| POST | `/api/dev/seed` | 샘플 팀·사용자·샘플 제출 생성 (프론트 연동 시험용) |

## 6. 메일 브리지 — 자체 도메인 (2026-10-29 결정, `docs/devlog/2026-10-29-mail-domain.md`)

```
받기:   담당자 흐름 ① → submit@jnuai-meetingfee.com → Cloudflare Email Routing
        → (운영) Email Worker가 메일 원본(raw MIME)을 POST /api/intake/mail 로 전달 (+ Gmail 백업 사본)
보내기: 백엔드 → Resend API → noreply@jnuai-meetingfee.com 발신
        "[발송요청] <REPLY_TOKEN> <MSGID>" → 담당자 메일 → 흐름 ② → 학생에게 담당자 이름으로 회신
```

```python
class MailBridge(Protocol):
    def parse_incoming(self, raw_mime: bytes) -> IncomingMail: ...   # 웹훅으로 받은 원본 → FROM/TO/RECEIVED/MSGID/첨부
    def request_reply(self, manager_email: str, msgid: str, body: str) -> None: ...  # Resend로 발송요청
```

- 웹훅은 **백엔드**가 받는다(프론트와 무관). 주소에 비밀 키를 붙이고, MSGID로 중복을 막는다.
- Worker는 첨부를 풀지 않고 **원본을 그대로** 넘긴다. 무료 Worker는 CPU·메모리가 작아서다. 파싱은 파이썬에서 한다.
- 원본 .eml과 첨부는 `data/raw/`, `data/files/`에, 결과는 SQLite에 둔다. 모두 영구 볼륨에 둔다.
- 키: `backend/.env`의 `RESEND_API_KEY`, `REPLY_TOKEN`(커밋 금지). 발송 시험 스크립트: `experiments/mail_send/send_request.py`
- 서버 공개 주소가 생기기 전에는 Cloudflare가 Gmail로 전달하고, `/api/dev/intake` 업로드로 개발한다.

## 7. 작업 순서 (세션 단위로 하나씩)

**진행 상황 (2026-10-31):** 1~6 구현 완료(`back`). 72건 회귀는 Upstage fixture 생성(키 필요) 후 확인. 7은 웹훅(`POST /api/intake/mail`)까지, 회신은 잠정안(웹메일 열기 + 보냈음 표시). 8 남음.
- 쪽 이미지: LibreOffice가 HWP 5.0·HWPX를 못 읽어(DOCX도 한글 글꼴 누락) `app/review/pages.py`가 문서 리더 결과를 나눔고딕으로 다시 그린다.
- 위밋·캡스톤·AIM·해커톤은 확정 기준이 없어 동아리 기준으로 임시 판정한다(담당자 메모에 표시).
- 실행: `cd backend && uv run uvicorn app.main:app --reload` → http://localhost:8000/docs

| # | 작업 | 끝났다는 기준 |
|---|---|---|
| 1 | FastAPI 뼈대: `app/main.py`, config, db, models, `/api/health` | `uvicorn app.main:app` 실행, `/docs` 열림 |
| 2 | `review/` 이식: readers, upstage(캐시), conditions, verdict, draft | 실험 18케이스 × 4형식 72/72가 `pytest`에서 재현 (Upstage 응답은 캐시 fixture로) |
| 3 | LangGraph 그래프 + worker | `/api/dev/intake`로 넣은 파일이 `done`까지 진행 |
| 4 | P0 API: auth, teams, submissions 목록·상세, files(쪽 이미지·다운로드), reply 저장·전송(Fake 브리지), confirm | 프론트 문서 예시 JSON과 같은 모양 |
| 5 | P1 API: checks 수정, 팀 지정, rerun, summary, 팀 상세·별칭 | |
| 6 | 팀·프로그램 매칭 (`team_match.py`, 기준 `rules/teams.yaml`) | 프로그램은 ① 별첨 제목 단어(캡스톤·동아리·WE-Meet) ② 단어 없는 양식은 AIM·해커톤 팀 목록에서 팀명으로, 겹치는 팀(테라바이트)은 팀원 명단으로 ③ 담당자 메일함·메일 단어 순으로 정함. 팀은 제목·본문·파일명·회의록 팀명을 별칭·대소문자·공백 무시로 대조하고 긴 이름 우선. 못 정하면 미확정 |
| 7 | 메일 브리지 실제 구현 | 담당자 메일 → 화면 → [전송] → 학생 회신 E2E |
| 8 | Docker + 배포 | 담당자가 URL로 접속 |

**병렬 가능:** 프론트는 1번 이후 `/docs`가 열리면 바로 타입을 맞출 수 있다. 4번 전까지는 프론트 문서의 목 데이터로 진행한다.

## 8. 의존성 (추가 예정)

의존성은 **uv**로 관리한다(2026-10-30 전환). 정의는 `backend/pyproject.toml`에 있고, 정확한 버전은 `backend/uv.lock`에 고정된다. Python은 `backend/.python-version`(3.12)이다.

- 설치: `uv sync`
- 실행: `uv run …`
- 추가: `uv add <패키지>`
- 개발용 추가: `uv add --dev <패키지>`

현재는 실험용만 들어 있다. 1번 단계에서 아래를 `uv add`로 추가한다.

```
fastapi  uvicorn[standard]  sqlalchemy  pydantic-settings  python-multipart
langgraph  langgraph-checkpoint-sqlite
passlib[bcrypt] 또는 argon2-cffi   # 비밀번호 해시
pyjwt                               # 로그인 토큰
```

`uv add`가 `pyproject.toml`과 `uv.lock`을 함께 고친다. 두 파일 모두 커밋한다.
