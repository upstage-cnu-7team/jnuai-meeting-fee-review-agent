# 회의비 증빙 자동 검수 Agent

전남대학교 ○○○대학사업단 담당자가 받는 **회의비 증빙(회의록 + 영수증) 메일을 자동으로 모아 검수하고, 항목별 근거와 회신 초안을 만들어 주는 서비스**입니다. Upstage LLMOps 과정 2차 프로젝트, 7조.

- **데모:** https://meeting-fee-review-agent.vercel.app (담당자 계정으로 로그인. 시연용 계정은 따로 안내)
- **API 문서(Swagger):** https://api.jnuai-meetingfee.com/docs
- **기획서:** [docs/submission/proposal.md](docs/submission/proposal.md)
- 이 레포는 제출용 공개본입니다. `backend/`(FastAPI·검수 로직·메일 연동)와 `frontend/`(담당자 화면, React)를 한곳에 모았습니다. 실제 학생 정보와 내부 운영 기록은 뺐습니다.

---

## 1. 서비스 소개

### 문제

사업단은 학생 팀(58팀: 동아리 41·위밋 41(같은 팀)·캡스톤 9·해커톤 5·AIM 챌린지 3)에 회의비를 지원합니다. 학생은 회의 뒤 사업단 양식 회의록(HWP·PDF)에 영수증 사진을 붙여 담당자 학교 메일로 보냅니다. 담당자 2명이 이 메일을 한 건씩 열어 **지침 17개 항목**(평일·20시 전 결제, 1인 2만 원, 광주 북구 가맹점, 연구비카드, 참석자 전원 서명, 7일 안 제출 등)을 눈으로 확인하고, 문제가 있으면 보완 메일을 직접 씁니다.

### 해결

1. 학생은 **지금처럼** 담당자 메일로 보낸다(학생 쪽 변화 없음).
2. 서비스가 메일과 첨부를 자동으로 가져온다.
3. Upstage AI로 회의록·영수증 값을 읽고, **코드와 LLM이 지침 항목을 하나씩 판정**한다.
4. 담당자 화면에 프로그램·팀별로 정리하고, 항목별 근거(원본 위치)와 **회신 초안**을 보여 준다.
5. 담당자가 확인·수정한 뒤 학생에게 회신한다.

**AI는 결정하지 않습니다.** 근거를 정리하고 초안을 만들 뿐, 최종 확인과 회신은 담당자가 합니다. 애매하면 `확인필요`로 담당자에게 넘기고, 학생 회신에는 확실한 미충족만 넣습니다.

### 주요 기능

| 기능 | 내용 |
|---|---|
| 메일 자동 수집 | 담당자 학교 메일 → 팀명 필터 → 서비스 웹훅. 네이버 대용량 첨부 링크도 내려받음 |
| 양식·프로그램·팀 판별 | 사업단 양식(별첨 1-1) 일치 확인, 별첨 제목·팀명·참석자로 프로그램과 팀 결정 |
| 항목별 자동 판정 | 동아리 기준 v2(R01~R17, R21) — 적합 / 보완필요 / 부적합 / 확인필요 |
| 원본 미리보기 | HWP·PDF·스캔본을 쪽 이미지로, 판정 근거 위치로 바로 이동 |
| 회신 초안 | 미충족 항목만 학생용 문장으로, 확인필요는 담당자 메모로 |
| 담당자 수정 | 항목 결과를 바꾸면 종합 판정과 초안이 다시 계산됨 |
| 권한 | 동아리 담당자(동아리·AIM·해커톤), 위밋 담당자(위밋·캡스톤)는 자기 프로그램만 |

---

## 2. 아키텍처

```
학생 메일 ─▶ 담당자 학교 메일(OWA)
   └ 받은 편지함 규칙(팀 키워드) ─▶ 중계 계정(M365) ─▶ Power Automate(팀명 정밀 필터)
       └ submit@jnuai-meetingfee.com ─▶ Cloudflare Email Routing ─▶ Email Worker
           └ POST /api/intake/mail (원본 MIME) ─▶ FastAPI ─▶ 검수 대기열
                                                                 │
   ┌─────────────────────────────────────────────────────────────┘
   ▼
 LangGraph 검수 흐름 (회의록마다)
   load_files ─▶ extract(Upstage Information Extract + 영수증 사진 재추출)
     ├─ 디지털(HWP·PDF·DOCX) ─▶ read_local: 칸 안 그림으로 서명·영수증 확인
     └─ 스캔본 ─────────────────▶ ocr_signature: Upstage OCR 좌표 + 잉크 비율
   ─▶ judge_solar(Solar: 주류·장소·회의내용·식비/다과비)
   ─▶ match_team(프로그램·팀) ─▶ judge_code(기준 조건 판정) ─▶ draft(회신 초안)
   ▼
 SQLite ─▶ 담당자 화면(React, Vercel) ─ /api ─▶ Cloudflare Tunnel ─▶ FastAPI(Docker, Azure VM)
```

### 판정 원칙

- **계산은 코드, 의미 판단만 LLM.** 날짜·요일·시각·금액·1인당 한도·지역·회의 시간·승인번호·제출 기한은 파이썬이, 술집·주류, 회의 장소, 회의내용 구체성, 식비/다과비 구분만 Solar가 판단합니다. 글자로 분명한 위반(가게 이름의 '호프', 장소의 '카페')은 코드가 먼저 잡습니다.
- **추출값을 그대로 믿지 않습니다.** 서명·영수증 첨부는 문서 리더로 **칸 안에 그림이 있는지** 직접 확인합니다. 영수증 사진은 문서 전체와 별도로 **사진만 원본 해상도로 한 번 더** 읽습니다.
- **애매한 구분은 두 방식으로 계산합니다.** 식비/다과비가 엇갈리면 두 계산을 나란히 보여 주고 확인필요로 둡니다.
- 판정 결과마다 **사용한 기준 버전과 모델**을 기록합니다. 기준은 지침 HWP에서 뽑은 초안을 **담당자가 확정**한 뒤에만 씁니다.
- 학생 이름·학번·서명·카드번호를 다루므로 로그에 원문을 남기지 않고, API 응답에서 학번·카드번호를 가립니다.

### 기술 스택

| 영역 | 선택 |
|---|---|
| 웹 서버 | FastAPI, Uvicorn |
| AI | Upstage Information Extract(문서 값 추출), Solar `solar-pro4`(의미 판단), Document OCR(스캔본 서명 좌표) |
| 흐름 | LangGraph (형식 분기, 회의록별 판정) |
| DB | SQLite + SQLAlchemy (`DATABASE_URL`로 Postgres 전환 가능) |
| 문서 읽기 | olefile(HWP 5.0)·python-docx·pdfplumber·pypdfium2, 자체 HWP 렌더러(reportlab) |
| 인증 | 아이디·비밀번호(argon2) + JWT, 이미지는 서명 URL(30분) |
| 메일 | Power Automate(중계), Cloudflare Email Routing + Email Worker(수신), Resend(발신, 보류) |
| 배포 | Docker(Azure VM) + Cloudflare Tunnel(`api.jnuai-meetingfee.com`), 프론트는 Vercel |
| 프론트 | React 19, Vite, TanStack Query, TypeScript |
| 패키지 | uv (`pyproject.toml` + `uv.lock`, Python 3.12) |

### 폴더

```
frontend/         담당자 화면 (React + Vite, Vercel 배포)
backend/
  app/
    api/          API 라우터 (docs/frontend-api.md와 1:1)
    graph/        LangGraph 검수 흐름
    review/       판정 로직: upstage.py(호출·캐시) readers.py(칸 그림) conditions.py(조건)
                  pipeline.py(추출) draft.py(회신 초안) hwp_render.py(미리보기)
    mail/         메일 접수·대용량 링크
  minutes_review/extract/   HWP·HWPX·DOCX·PDF 리더
  rules/          판정 기준(aicollege_club.yaml), 팀 목록(teams.yaml, 공개본은 팀원 명단을 비움)
  tools/          샘플 생성·fixture 생성·보관 메일 관리
  tests/          pytest (가상 회의록 72건 회귀 포함)
infra/
  email-worker/   Cloudflare Email Worker
  server/         배포 스크립트
docs/             설계·API 약속·설명서
```

---

## 3. 실행 방법

### 로컬

```bash
cd backend
uv sync                     # .venv 생성 + 의존성 설치 (uv.lock 기준)
cp .env.example .env        # 아래 환경변수 채우기
uv run pytest -q            # 단위 + 72건 회귀 (Upstage 응답은 tests/fixtures 캐시, 키 불필요)
uv run uvicorn app.main:app --reload    # http://localhost:8000/docs
```

- `.env`의 `SEED_PASSWORD_*`를 채우면 첫 실행 때 계정(`club-manager`, `wemeet-manager`, `admin`)이 만들어집니다.
- 메일 없이 시험하려면 `/docs`에서 로그인한 뒤 `POST /api/dev/intake`로 회의록 파일을 올립니다.
- 프론트엔드: 다른 터미널에서 아래를 실행하고 http://localhost:5173 을 연다(개발 서버가 `/api`를 `localhost:8000`으로 넘김).

```bash
cd frontend
npm install
npm run dev
```

### 서버 배포

```bash
infra/server/deploy.sh <user>@<host>     # 코드 복사 → Docker 빌드 → 컨테이너 재시작 → 터널 연결 확인
```

- 컨테이너 이름 `meetingfee`, 데이터(SQLite·원본 파일)는 볼륨에 둡니다.
- 프론트엔드는 Vercel에 `frontend/`를 연결해 배포합니다. `frontend/vercel.json`이 `/api`를 백엔드 주소로 넘깁니다.
- 메일 수신 Worker 설정은 [infra/email-worker/README.md](infra/email-worker/README.md)를 따릅니다.

---

## 4. 환경변수

`backend/.env` (예시: `backend/.env.example`). **`.env`는 커밋하지 않습니다.**

| 변수 | 필수 | 설명 |
|---|---|---|
| `UPSTAGE_API_KEY` | ✓ | Upstage 콘솔에서 발급 |
| `SECRET_KEY` | ✓ | 로그인 토큰·서명 URL 비밀키 (운영은 길고 무작위인 값) |
| `SEED_PASSWORD_CLUB` / `SEED_PASSWORD_WEMEET` / `SEED_PASSWORD_ADMIN` | 첫 실행 | 계정 초기 비밀번호. 비어 있으면 그 계정은 만들지 않음 |
| `INTAKE_SECRET` | 메일 수집 | Email Worker가 `X-Intake-Secret` 헤더로 보내는 값 |
| `INTAKE_SINCE` | | 이 시각(KST) 이전 메일은 접수하지 않음. 예 `2026-10-30T00:30` |
| `MANAGER_MAILBOXES` | 메일 수집 | 담당자 원래 주소 → 메일함(프로그램 구분) |
| `DATABASE_URL` | | 기본 `sqlite:///backend/data/app.db` |
| `DATA_DIR` | | 원본 파일·쪽 이미지 저장 위치 |
| `CORS_ORIGINS` | | 기본 `localhost:5173`, `localhost:3000` (Vercel은 같은 출처 프록시라 불필요) |
| `DEV_ENDPOINTS` | | `/api/dev/*` 켜기 (운영은 `false`) |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` / `GMAIL_POLL_MINUTES` | | 웹훅 이전 임시 수집용 Gmail |

---

## 5. API

전체 약속과 응답 예시는 [docs/frontend-api.md](docs/frontend-api.md), 실행 중 스키마는 `/docs`(Swagger)에 있습니다. 모든 경로는 `/api` 아래입니다.

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/auth/login` | 로그인 → JWT |
| GET | `/auth/me` | 내 계정·맡은 프로그램 |
| GET | `/programs/{program}/summary` | 요약 카드(오늘 접수·미확인·판정별 수) |
| GET | `/programs/{program}/teams` | 팀 목록 |
| GET | `/programs/{program}/submissions` | 제출 목록(검색·정렬·회신·날짜 필터) |
| GET | `/programs/unassigned/submissions` | 프로그램 미확정 목록 |
| GET | `/submissions/{id}` | 제출 상세(추출값·조건별 결과·회신 초안) |
| PATCH | `/submissions/{id}/checks/{check_id}` | 담당자가 항목 결과 수정 |
| PATCH | `/submissions/{id}` | 프로그램·팀 지정 |
| POST | `/submissions/{id}/rerun` | 다시 검수 |
| PUT | `/submissions/{id}/reply` | 회신 초안 저장 |
| POST | `/submissions/{id}/reply/regenerate` | 회신 초안 다시 만들기 |
| POST | `/submissions/{id}/reply/mark-sent` | 보냈음 표시 |
| POST | `/submissions/{id}/confirm` | 확인완료 |
| GET | `/files/{file_id}/pages/{n}.png` | 원본 쪽 이미지(서명 URL) |
| GET | `/files/{file_id}/download` | 원본 다운로드 |
| GET | `/teams/{team_id}` · PUT `/teams/{team_id}/aliases` | 팀 상세·별칭 |
| GET | `/programs/{program}/rules` | 확정 기준 보기 |
| POST | `/intake/mail` | 메일 수신 웹훅(Email Worker 전용) |

---

## 6. 팀원 (7조)

| 이름 | 역할 |
|---|---|
| 박종희 | 백엔드(FastAPI·LangGraph·Upstage 검수 로직), 메일 연동, 배포 |
| 김동욱 | 서비스 디자인, 프론트엔드(담당자 화면) |
| 강지수 | AI 검수 정확도 — 놓치는 예시 서류 제작, 실험·측정 |

---

## 더 보기

| 문서 | 내용 |
|---|---|
| [docs/service-guide.md](docs/service-guide.md) | 서비스 설명서 — 흐름, 검수 조건 상세, 원칙 |
| [docs/direction.md](docs/direction.md) | 확정·잠정 결정 |
| [docs/frontend-api.md](docs/frontend-api.md) | 프론트 ↔ 백엔드 API 약속 |
| [docs/backend-plan.md](docs/backend-plan.md) | 백엔드 구조·DB·검수 그래프 |
| [docs/manual/manager-guide.html](docs/manual/manager-guide.html) | 담당자 사용설명서 |
| [backend/experiments/aicollege_upstage/README.md](backend/experiments/aicollege_upstage/README.md) | Upstage 실험 결과 |
