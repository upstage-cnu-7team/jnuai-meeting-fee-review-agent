# 회의비 증빙 자동 검수 — 프론트엔드 전달 문서

> **공개용 사본.** 정본은 비공개 백엔드 레포 `meeting-fee-review-agent-back`의 `docs/frontend-api.md`다. 바뀌면 그쪽이 먼저 바뀌고 이 사본을 다시 맞춘다. 운영 주소·메일 경로 같은 내부 정보는 넣지 않는다.


- 작성: 2026-10-28
- 대상: 프론트엔드 담당 팀원
- 백엔드: Python · FastAPI · SQLite(SQLAlchemy) · LangGraph · Upstage API
- 상태: **초안 v0.2** (2026-10-31: 백엔드 구현 반영 — mark-sent 오류, send 503, rules `note`, 쪽 이미지 미리보기) (2026-10-30: 계정 2개·프로그램 5개, 회신 잠정안, FE 8장 질문 답변 반영). API 모양은 이 문서를 기준으로 맞춘다. 바뀌면 이 문서를 먼저 고친다.

> 이 문서만 보고 화면을 만들 수 있게 썼다. 백엔드가 준비되기 전에는 맨 아래 **목 데이터**로 개발한다.

---

## 0. 서비스 한 줄 요약

학생이 담당자 학교 메일로 회의비 증빙(회의록 + 영수증)을 보내면, 서비스가 첨부를 자동으로 가져와 **AI로 검수**한다. 결과는 **프로그램 → 팀 → 제출 건**으로 보여 준다. 프로그램은 5개(동아리·AIM·해커톤·위밋·캡스톤)이고, 담당자는 자기가 맡은 프로그램만 본다. 담당자는 결과를 확인하고 회신 초안을 고친 뒤 **[전송]**을 누른다. 그러면 담당자 이름으로 학생에게 회신이 간다.

```
학생 메일 ─▶ 담당자 메일함 ─(Power Automate)─▶ 서비스 수집 ─▶ AI 검수 ─▶ [담당자 화면]
                                                                          │ 확인·수정
학생 ◀── 담당자 이름으로 회신 ◀─(Power Automate)── [전송] ◀────────────────┘
```

프론트는 **담당자 화면**만 만든다. 메일 수집, AI 검수, 메일 발송은 모두 백엔드 몫이다.

## 1. 사용자

| 사용자 | 수 | 보는 범위 |
|---|---|---|
| 동아리 담당자 (계정 1) | 1 | **동아리·AIM·해커톤** 3개 프로그램 |
| 위밋 담당자 (계정 2) | 1 | **위밋·캡스톤** 2개 프로그램 |
| 관리자(우리 팀) | 소수 | 전부 + 기준 관리 |

- 같은 팀이 두 프로그램에 모두 있을 수 있다. 팀은 **프로그램별로 따로** 취급한다.
- 담당자는 PC에서 쓴다. **데스크톱 우선**으로 만들고, 모바일은 목록 조회만 깨지지 않게 한다.

---

## 2. 꼭 구분해야 하는 상태값 4가지

한 제출 건에는 상태가 4종류 있다. 섞이지 않게 **배지를 따로** 보여 준다.

### 2-1. 처리 상태 `processing_status` — 서버가 AI 검수를 끝냈나

| 값 | 표시 | 설명 |
|---|---|---|
| `queued` | 대기 중 | 수집됨, 검수 순서 기다림 |
| `processing` | 검수 중 | 1건에 20~60초 걸린다 |
| `done` | 완료 | 판정 결과 있음 |
| `failed` | 처리 실패 | Upstage 오류 등. 원본 파일은 볼 수 있다. 담당자가 직접 보거나 [다시 검수] |

### 2-2. AI 판정 `verdict` — 서류가 기준에 맞나 (`done`일 때만)

| 값 | 표시 | 색(제안) | 뜻 |
|---|---|---|---|
| `pass` | 적합 | 초록 | 모든 조건 충족 |
| `needs_fix` | 보완필요 | 주황 | 고치면 되는 문제(서명 누락, 승인번호 없음 등) |
| `reject` | 부적합 | 빨강 | 인정 불가(주말 사용, 20시 이후, 주류 등) |
| `review` | 확인필요 | 회색/보라 | AI가 확신 못 함. **담당자가 봐야 함** |

종합 판정은 항목 중 가장 나쁜 것을 따른다. 우선순위는 `reject` > `needs_fix` > `review` > `pass`이다.

### 2-3. 담당자 확인 `review_status` — 담당자가 이 건을 봤나

| 값 | 표시 |
|---|---|
| `pending` | 확인필요 |
| `confirmed` | 확인완료 |

> 주의: AI 판정의 "확인필요(`review`)"와 담당자 확인의 "확인필요(`pending`)"는 **이름이 같지만 다른 것**이다. 화면에서는 각각 "AI: 확인필요"와 "담당자 미확인" 정도로 구분하는 것을 추천한다. 문구는 프론트에서 정해도 된다.

### 2-4. 회신 상태 `reply_status`

| 값 | 표시 | 설명 |
|---|---|---|
| `none` | — | 초안 없음 (검수 전) |
| `draft` | 초안 있음 | 보낼 수 있음 |
| `sending` | 전송 중 | [전송] 누름. 실제 발송까지 1~5분 |
| `sent` | 전송 완료 | |
| `failed` | 전송 실패 | 다시 시도 가능 |
| `not_needed` | 회신 안 함 | 적합이라 확인완료만 처리한 경우 |

---

## 3. 화면 구성

```
┌──────────────────────────────────────────────────────────────┐
│ 상단바: 서비스명 · [맡은 프로그램 탭] · 담당자 이름 · 로그아웃   │
├────────────┬─────────────────────────────────────────────────┤
│ 팀 목록     │ (A) 제출 목록  또는  (B) 제출 상세                 │
│ (사이드바)  │                                                 │
└────────────┴─────────────────────────────────────────────────┘
```

### 계정과 권한 (2026-10-30 결정)

- 계정은 **2개**다. 담당자 한 명에게 하나씩 준다(아이디·비밀번호는 우리가 만들어 전달).

  | 계정 | `programs` | 보이는 탭 |
  |---|---|---|
  | 동아리 담당자 | `["club", "aim", "hackathon"]` | 동아리 · AIM · 해커톤 |
  | 위밋 담당자 | `["wemeet", "capstone"]` | 위밋 · 캡스톤 |

- 상단 탭은 `user.programs` 순서대로 그린다. 첫 화면은 `programs[0]`이다.
- 담당자는 **자기 메일함으로 온 제출만** 본다. 다른 담당자의 프로그램 경로나 제출 건을 요청하면 서버가 **403**을 준다.
- 같은 이름 팀(예: 테라바이트는 동아리·AIM·해커톤에 다 있다)은 프로그램마다 **다른 팀**으로 취급한다(`team.id`가 다르다).
- 서버가 프로그램을 정하지 못한 제출(양식 제목·메일 단어로 판단 불가, 또는 AIM·해커톤에 모두 있는 팀을 팀원 명단으로 구분하지 못함)은 `program: null`로 온다. 이유는 `reply.internal_notes` 맨 앞과 `team.match_reason`에 한국어로 온다. 그 담당자의 **"프로그램 미확정"** 목록에 모인다: `GET /api/programs/unassigned/submissions`(로그인한 담당자 것만). 담당자가 상세에서 프로그램과 팀을 지정한다(`PATCH /submissions/{id}` with `{"program": "aim", "team_id": "..."}`).
- 관리자 계정(우리 팀)은 `role: "admin"`, `programs`는 5개 전부다.

### S0. 로그인

- 아이디와 비밀번호를 입력하고 `POST /api/auth/login`을 부른다.
- 토큰은 메모리나 `sessionStorage`에 둔다. 401을 받으면 로그인 화면으로 보낸다.
- 담당자는 자기 프로그램만 볼 수 있다. 관리자는 탭 두 개를 모두 본다.

### S1. 메인 — 프로그램 탭 + 팀 사이드바 + 제출 목록

**상단 요약 카드** (`GET /api/programs/{program}/summary`)
- 오늘 접수
- 담당자 미확인
- AI 확인필요
- 보완필요
- 부적합
- 전송 실패

카드를 누르면 그 조건으로 목록을 필터한다.

**팀 사이드바** (`GET /api/programs/{program}/teams`)
- 팀 이름과 미확인 건수 배지를 보여 준다. 미확인이 많은 순 → 이름순으로 정렬한다.
- 맨 위에 "전체", 맨 아래에 **"팀 미확정"**을 둔다. AI가 팀을 못 정한 제출이 "팀 미확정"에 들어간다.
- 팀 이름이 길면 말줄임하고, 마우스를 올리면 전체 이름을 보여 준다. 팀은 ~40개라 사이드바에 검색창을 둔다.

**제출 목록** (`GET /api/programs/{program}/submissions?...`)

| 열 | 내용 |
|---|---|
| 접수 일시 | `received_at` (예: 10/28 14:03) |
| 팀 | 팀 이름. 팀 미확정이면 "미확정" 배지 |
| 회의일 / 금액 | `summary.meeting_date`, `summary.total_amount` |
| AI 판정 | 2-2 배지. 처리 중이면 스피너 |
| 걸린 항목 | 미충족 조건 이름 최대 2개 + "외 N" |
| 담당자 확인 | 확인필요 / 확인완료 |
| 회신 | 2-4 배지 |

- 정렬은 **서버가 한다**(`sort=default`). 기본 순서: **처리 실패** → **담당자 미확인**(부적합 → 보완필요 → AI 확인필요 → 적합 → 검수 중·대기) → **확인완료**. 같은 그룹 안에서는 접수 최신순이다. 프론트는 받은 순서 그대로 그린다.
- 필터: 판정, 담당자 확인, 회신 상태, 기간.
- 행을 누르면 S2로 간다. URL은 `/submissions/{id}`로 해서 새로고침해도 유지되게 한다.
- `queued`/`processing` 건이 목록에 있으면 **15초마다 목록을 다시 불러온다**. 없으면 60초마다.

### S2. 제출 상세 (가장 중요한 화면)

`GET /api/submissions/{id}`

```
┌ 헤더: 팀명 · 접수 일시 · 보낸 사람 · AI 판정 배지 · 담당자 확인 배지 ─────┐
│ 메일 제목 / 본문 (접기 가능)                                               │
├──────────────────────────────┬───────────────────────────────────────────┤
│ 왼쪽: 원본 보기               │ 오른쪽: 검수 결과                          │
│  - 첨부 파일 탭(회의록, 영수증) │  - 추출 요약(회의일시, 장소, 참석자, 금액)   │
│  - 쪽 이미지, 확대/축소        │  - 조건별 결과 목록 (R01~R17)               │
│  - [원본 다운로드]             │  - 회신 초안 편집기 + [전송]               │
└──────────────────────────────┴───────────────────────────────────────────┘
```

**왼쪽: 원본 보기**
- `attachments[]`마다 탭을 둔다. 파일 형식(hwp, pdf, docx, 이미지)과 상관없이 서버가 **쪽 이미지(PNG)**로 바꿔 준다.
  - 이미지 주소: 상세 응답의 `attachments[].pages[].url`을 **그대로 `<img src>`에 넣는다.** 서버가 만든 **서명 URL**(`…/pages/1.png?exp=…&sig=…`)이라 로그인 헤더가 필요 없다. 30분 뒤 만료되며, 상세를 다시 불러오면 새 주소가 온다. 이미지가 403이면 상세를 다시 불러온다.
  - 쪽 이미지는 150dpi PNG(A4 약 1240×1754px)이고 크기는 `pages[].width/height`로 온다.
  - PDF·스캔·사진은 원본 그대로 그린다. **HWP·HWPX·DOCX는 서버가 표·칸·그림을 다시 그린 미리보기**라 원래 모양과 다를 수 있다(첫 줄에 안내 문구가 찍힌다). 정확한 모양은 [원본 다운로드]로 본다.
  - 원본 파일: `attachments[].download_url`(서명 URL, 같은 방식)
- 조건 결과의 근거에 `evidence.page`가 있으면, 클릭할 때 그 쪽으로 이동한다. 박스 강조(`evidence.bbox`)는 **있으면 쓰는 선택 기능**이다. 좌표는 쪽 이미지 기준 **0~1 비율** `[x0, y0, x1, y1]`, 왼쪽 위가 원점이다.

**오른쪽 ①: 추출 요약** (`extracted`)
- 팀명, 회의명, 회의일시(시작~종료), 장소
- 참석자 표: 소속, 학번, 이름, 서명 ✓/✗
- 영수증: 가맹점, 주소, 거래일시, 카드종류, 승인번호, 합계, 품목
- 결제자: 소속, 이름, 서명 ✓/✗
- 카드번호는 서버가 **마스킹해서** 준다. 프론트에서 따로 처리하지 않는다.

**오른쪽 ②: 조건별 결과** (`checks[]`)
- 한 줄 형식: `[결과 아이콘] 조건 이름 · (판정 주체) · 근거 한 줄`
- 결과 값:

| `result` | 아이콘(제안) | 뜻 |
|---|---|---|
| `met` | ✓ 초록 | 충족 |
| `unmet` | ✗ 빨강/주황(`severity`에 따라) | 미충족 |
| `review` | ? 회색 | AI가 판단 못 함 |
| `excluded` | — 흐리게 | 이번 기준에서 제외된 조건 |

- `unmet` → `review` → `met` 순으로 정렬한다. `met`은 기본으로 접어 둔다("충족 12개 보기").
- 줄을 펼치면 `evidence`를 보여 준다:
  - 찾은 값(`found`)
  - 기준(`expected`)
  - 어디서(`field`, `page`)
  - 지침 원문(`rule_source`)
  - 판정 주체(`by`: 코드 / AI / 추출)
- **담당자 수정**: 각 줄에 [충족으로] [미충족으로] 버튼과 메모 입력을 둔다.
  - `PATCH /api/submissions/{id}/checks/{check_id}`를 부른다.
  - 응답으로 **다시 계산된 종합 판정과 새 초안**이 온다. 화면을 그 값으로 바꾼다.
  - 담당자가 바꾼 항목에는 "담당자 수정" 표시를 하고, 원래 AI 결과도 함께 보여 준다(`ai_result`).

> **회신 방식 (2026-10-30, 잠정 · 논의 필요)**
> 담당자 메일이 학교 자체 Exchange라 **담당자 이름 자동 발송은 불가**하다. 우선 **"웹메일에서 열기"**로 간다. 학교 웹메일 지원 여부는 시험 전이고, 방식은 담당자와 논의 후 확정한다.
> - [웹메일에서 열기]: 서버가 주는 `reply.compose_url`(담당자 OWA 새 메일 창, 받는 사람·제목·본문 채움)을 새 탭으로 연다. 담당자가 웹메일에서 보낸다.
> - [초안 복사]: 본문이 길어 주소에 다 안 들어가면(`reply.compose_truncated=true`) 열기 대신, 또는 함께 쓴다. 웹메일 주소 길이 제한(한글 본문 약 200자)이 있어서다.
> - [보냈음 표시]: 담당자가 직접 보낸 뒤 누른다 → `POST /submissions/{id}/reply/mark-sent` → `reply_status=sent`. 서비스는 실제 발송 여부를 알 수 없다.
> - 아래 `POST /reply/send`(서비스 직접 발송)는 **보류**다. 담당자 동의가 있으면 `noreply@` 발송 + 담당자 참조 방식으로 쓸 수 있게 남겨 둔다.
> - 프론트는 전송 버튼 영역을 이 세 버튼으로 바꿀 수 있게 만들어 둔다. 시연은 목(MSW)으로 진행한다.

**오른쪽 ③: 회신 초안** (`reply`)
- 받는 사람은 읽기 전용(`reply.to`), 제목과 본문은 편집할 수 있다.
- 서버가 만든 초안에는 **미충족 항목만** 들어간다. AI 확인필요 항목은 학생에게 보내지 않고 `reply.internal_notes`(담당자 메모)로만 보여 준다.
- 저장: `PUT /api/submissions/{id}/reply`. 자동 저장(입력 멈추고 2초 뒤)을 추천한다.
- **[전송]** (`POST /api/submissions/{id}/reply/send`):
  - 누르면 확인 모달을 띄운다: "○○팀(학생 주소)에게 담당자님 이름으로 회신합니다."
  - 응답은 202이고 `reply_status=sending`이다. 이후 상세 화면을 15초마다 다시 불러와 `sent`/`failed`를 확인한다.
  - `sending`/`sent`일 때는 편집과 전송 버튼을 막는다.
- **[확인완료만]** (`POST /api/submissions/{id}/confirm` with `{"reply": "not_needed"}`): 적합이라 회신이 필요 없을 때 쓴다.
- [전송]이 성공하면 서버가 자동으로 `review_status=confirmed`로 바꾼다.

**헤더 동작**
- [다시 검수] `POST /api/submissions/{id}/rerun`: `failed` 상태이거나 기준이 바뀐 뒤 쓴다.
- [팀 지정/변경] `PATCH /api/submissions/{id}` with `{"team_id": ...}`: 팀이 미확정이거나 잘못 잡혔을 때 쓴다. 팀 목록에서 고른다.
- 같은 팀의 **이전 제출**을 링크로 보여 준다(`previous_submissions`). 보완 후 재제출인지 알 수 있다.

### S3. 팀 상세 (P1)

`GET /api/teams/{team_id}`
- 팀 이름, 별칭, 등록된 학생 메일 주소
- 제출 이력 타임라인: 접수일, 회의일, 금액, 판정, 회신
- 별칭 추가와 삭제 (`PUT /api/teams/{team_id}/aliases`). 메일이나 회의록에서 팀을 알아보는 데 쓰인다.

### S4. 기준 보기 (P2, 관리자)

`GET /api/programs/{program}/rules`
- 현재 확정 기준 버전과 조건 17개(이름, 판정 주체, 등급, 파라미터, 지침 원문)
- 처음에는 **읽기 전용**으로 만든다. 수정 화면은 나중에 한다.

### 우선순위

| 우선 | 화면 |
|---|---|
| **P0** | S0 로그인, S1 목록, S2 상세(원본, 결과, 초안, 전송) |
| P1 | 담당자 수정(PATCH checks), 팀 지정, S3 팀 상세, 요약 카드 |
| P2 | S4 기준 보기, 원본 박스 강조 |

---

## 4. API 명세

### 공통

- Base URL: `/api` (개발 `http://localhost:8000/api`). FastAPI 자동 문서는 `http://localhost:8000/docs`에서 볼 수 있다. 백엔드가 올라오면 이걸 최종 기준으로 삼는다.
- 인증: `Authorization: Bearer <token>`
- 시간: ISO 8601 + 한국 시간대. 예: `"2026-10-28T14:03:00+09:00"`
- 금액: 정수(원)
- 프로그램 값: `club`(동아리) | `aim`(AIM) | `hackathon`(해커톤) | `wemeet`(위밋) | `capstone`(캡스톤)
- 오류 형식(모든 4xx/5xx):
  ```json
  { "error": { "code": "SUBMISSION_NOT_FOUND", "message": "제출 건을 찾을 수 없습니다." } }
  ```
  `message`는 그대로 화면에 띄워도 되는 한국어 문장이다.
- 목록 페이지네이션: `?page=1&size=50` → 응답 `{ "items": [...], "total": 123, "page": 1, "size": 50 }`

### 엔드포인트 한눈에

| 메서드 | 경로 | 화면 | 우선 |
|---|---|---|---|
| POST | `/auth/login` | S0 | P0 |
| GET | `/auth/me` | 공통 | P0 |
| GET | `/programs/{program}/summary` | S1 | P1 |
| GET | `/programs/{program}/teams` | S1 | P0 |
| GET | `/programs/{program}/submissions` | S1 | P0 |
| GET | `/submissions/{id}` | S2 | P0 |
| GET | `/files/{file_id}/pages/{n}.png` | S2 | P0 |
| GET | `/files/{file_id}/download` | S2 | P0 |
| PUT | `/submissions/{id}/reply` | S2 | P0 |
| POST | `/submissions/{id}/reply/mark-sent` | S2 | P0 (잠정 회신) |
| POST | `/submissions/{id}/reply/send` | S2 | 보류 (503) |
| POST | `/submissions/{id}/confirm` | S2 | P0 |
| PATCH | `/submissions/{id}/checks/{check_id}` | S2 | P1 |
| PATCH | `/submissions/{id}` | S2 | P1 |
| POST | `/submissions/{id}/reply/regenerate` | S2 | P1 |
| POST | `/submissions/{id}/rerun` | S2 | P1 |
| GET | `/teams/{team_id}` | S3 | P1 |
| PUT | `/teams/{team_id}/aliases` | S3 | P1 |
| GET | `/programs/{program}/rules` | S4 | P2 |
| GET | `/programs/unassigned/submissions` | 프로그램 미확정 | P1 |

### POST `/auth/login`

```json
// 요청
{ "username": "club-manager", "password": "••••" }
// 응답 200
{
  "access_token": "eyJ...",
  "user": { "name": "동아리 담당자", "role": "manager", "programs": ["club", "aim", "hackathon"] }
}
// 위밋 담당자 계정이면
{
  "access_token": "eyJ...",
  "user": { "name": "위밋 담당자", "role": "manager", "programs": ["wemeet", "capstone"] }
}
```
`401 INVALID_CREDENTIALS`

### GET `/auth/me`
응답은 위의 `user`와 같다.

### GET `/programs/{program}/summary`

```json
{
  "today_received": 4,
  "unconfirmed": 7,
  "ai_review": 2,
  "needs_fix": 3,
  "reject": 1,
  "reply_failed": 0,
  "processing": 1
}
```

### GET `/programs/{program}/teams`

```json
[
  { "id": "t_club_007", "name": "코딩하는감자들", "unconfirmed": 2, "total": 5, "last_received_at": "2026-10-28T14:03:00+09:00" },
  { "id": null, "name": "팀 미확정", "unconfirmed": 1, "total": 1, "last_received_at": "2026-10-28T09:12:00+09:00" }
]
```
"팀 미확정" 항목의 `id`는 `null`이다. 목록을 조회할 때는 `team_id=unassigned`로 보낸다.

### GET `/programs/{program}/submissions`

쿼리(모두 선택):

| 이름 | 예 | 설명 |
|---|---|---|
| `team_id` | `t_club_007`, `unassigned` | |
| `verdict` | `reject,needs_fix` | 쉼표로 여러 개 |
| `review_status` | `pending` | |
| `reply_status` | `failed` | |
| `from`, `to` | `2026-10-01` | 접수일 기준 |
| `q` | `감자` | 팀명, 보낸 사람, 제목 검색 |
| `sort` | `default`(기본), `received_desc`, `received_asc` | 서버 정렬. 페이지가 나뉘어도 순서가 맞다 |
| `page`, `size` | | |

```json
{
  "items": [
    {
      "id": "s_20261028_0012",
      "program": "club",
      "team": { "id": "t_club_007", "name": "코딩하는감자들" },
      "received_at": "2026-10-28T14:03:00+09:00",
      "sender": { "name": "김학생", "email": "student@example.ac.kr" },
      "subject": "[동아리] 코딩하는감자들 10월 3차 회의비 증빙 제출합니다",
      "processing_status": "done",
      "verdict": "needs_fix",
      "review_status": "pending",
      "reply_status": "draft",
      "summary": {
        "meeting_date": "2026-10-27",
        "total_amount": 64000,
        "attendee_count": 4,
        "failed_checks": ["참석자 전원 서명", "승인번호 표기"],
        "review_checks": [],
        "failed_count": 2,
        "review_count": 0
      }
    }
  ],
  "total": 1, "page": 1, "size": 50
}
```
`processing_status`가 `done`이 아니면 `verdict`와 `summary`는 `null`일 수 있다.

### GET `/submissions/{id}` (상세)

```json
{
  "id": "s_20261028_0012",
  "program": "club",
  "team": { "id": "t_club_007", "name": "코딩하는감자들", "match": "auto", "match_reason": "메일 제목과 회의록 팀명 일치" },
  "received_at": "2026-10-28T14:03:00+09:00",
  "sender": { "name": "김학생", "email": "student@example.ac.kr" },
  "mail": {
    "subject": "[동아리] 코딩하는감자들 10월 3차 회의비 증빙 제출합니다",
    "body_text": "안녕하세요 담당자님, ... "
  },
  "attachments": [
    { "file_id": "f_01", "name": "회의록_10월3차.hwp", "kind": "minutes", "format": "hwp", "page_count": 2, "size": 48213,
      "pages": [
        { "n": 1, "url": "/api/files/f_01/pages/1.png?exp=1793300000&sig=ab12…", "width": 1240, "height": 1754 },
        { "n": 2, "url": "/api/files/f_01/pages/2.png?exp=1793300000&sig=cd34…", "width": 1240, "height": 1754 }
      ],
      "download_url": "/api/files/f_01/download?exp=1793300000&sig=ef56…" },
    { "file_id": "f_02", "name": "영수증.jpg", "kind": "receipt", "format": "image", "page_count": 1, "size": 812001,
      "pages": [ { "n": 1, "url": "/api/files/f_02/pages/1.png?exp=…&sig=…", "width": 1240, "height": 1650 } ],
      "download_url": "/api/files/f_02/download?exp=…&sig=…" }
  ],
  "processing_status": "done",
  "processing_error": null,
  "verdict": "needs_fix",
  "review_status": "pending",
  "reply_status": "draft",
  "updated_at": "2026-10-28T14:05:12+09:00",
  "rule_set": { "id": "rs_club_v1", "version": 1, "confirmed_at": "2026-10-28T11:00:00+09:00" },
  "extracted": {
    "team_name": "코딩하는감자들",
    "meeting_title": "10월 3차 정기 회의",
    "meeting_date": "2026-10-27",
    "start_time": "17:00",
    "end_time": "18:10",
    "place": "공과대학 7호관 세미나실",
    "content": "1. 공모전 주제 확정 ...",
    "attendees": [
      { "affiliation": "인공지능학부", "student_id": "2023****", "name": "김학생", "has_signature": true },
      { "affiliation": "인공지능학부", "student_id": "2023****", "name": "이학생", "has_signature": false }
    ],
    "writer_name": "김학생",
    "used_amount": 64000,
    "payer": { "affiliation": "인공지능학부", "name": "김학생", "has_signature": true },
    "receipt": {
      "attached": true,
      "type": "신용카드 매출전표",
      "merchant_name": "○○식당",
      "merchant_address": "광주광역시 북구 용봉로 ...",
      "card_type": "연구비카드",
      "card_number": "9410-****-****-1234",
      "approval_number": "",
      "transaction_datetime": "2026-10-27T18:25:00+09:00",
      "items": [ { "name": "제육볶음", "quantity": 4, "amount": 64000 } ],
      "total": 64000
    }
  },
  "checks": [
    {
      "check_id": "R14",
      "name": "참석자 전원 서명 (자필·전자, 워드 작성 불가)",
      "by": "extract+code",
      "severity": "needs_fix",
      "result": "unmet",
      "ai_result": "unmet",
      "overridden": false,
      "message": "참석자 4명 중 1명(이학생) 서명이 없습니다.",
      "evidence": {
        "field": "attendees[1].has_signature",
        "found": "서명 칸 비어 있음",
        "expected": "참석자 전원 서명",
        "file_id": "f_01", "page": 2, "bbox": null,
        "rule_source": "참석자명단(서명 포함)"
      },
      "manager_note": null
    },
    {
      "check_id": "R08",
      "name": "1인당 20,000원 이내",
      "by": "code",
      "severity": "reject",
      "result": "met",
      "ai_result": "met",
      "overridden": false,
      "message": "64,000원 ÷ 4명 = 16,000원",
      "evidence": { "field": "receipt.total", "found": "16000", "expected": "≤ 20000", "file_id": "f_02", "page": 1, "bbox": null, "rule_source": "1인당 2만원 이내" },
      "manager_note": null
    }
  ],
  "reply": {
    "status": "draft",
    "to": "student@example.ac.kr",
    "subject": "RE: [동아리] 코딩하는감자들 10월 3차 회의비 증빙 제출합니다",
    "body": "안녕하세요, 인공지능혁신융합대학사업단입니다.\n제출해 주신 회의비 증빙을 확인한 결과 아래 항목의 보완이 필요합니다.\n\n1. 참석자 서명: 이학생 님의 서명이 없습니다.\n...",
    "internal_notes": ["R09 식비/다과비 구분: AI가 확신하지 못함 — 품목 확인 필요"],
    "edited_by_manager": false,
    "sent_at": null,
    "error": null
  },
  "previous_submissions": [
    { "id": "s_20261021_0004", "received_at": "2026-10-21T10:00:00+09:00", "verdict": "pass", "reply_status": "not_needed" }
  ]
}
```

필드 메모
- `team.match`는 `auto`(AI가 정함), `manual`(담당자가 정함), `none`(미확정) 중 하나다.
- `attachments[].kind`는 `minutes`(회의록), `receipt`(영수증), `other` 중 하나다. 회의록 파일 안에 영수증이 붙어 있으면 `minutes` 하나만 온다.
- `checks[].by`는 `code`(계산), `ai`(Solar 판단), `extract+code`(추출값 + 코드 확인) 중 하나다. 화면에는 "자동 계산", "AI 판단", "자동 추출" 정도로 표시한다.
- `checks[].severity`는 미충족일 때의 무게다. `reject`면 빨강, `needs_fix`면 주황으로 칠한다.
- `evidence.alternatives`(배열 또는 null): 구분이 애매해 **두 방식으로 모두 계산한 결과**다. 예: R09 식비/다과비가 애매하면 `[{"label":"식비로 보면","result":"unmet","detail":"…","expected":"…"}, {"label":"다과비로 보면","result":"met",…}]`. 둘 다 위반이면 `result=unmet`, 둘 다 통과면 `met`, **엇갈리면 `review`**다. 화면에는 두 줄을 나란히 보여 담당자가 어느 쪽인지 고르게 한다(2026-10-31).
- `checks[]` 맨 앞에 **`F00` 양식 확인**(사업단 별첨 1-1 양식과 칸 대조)이 온다. 결과는 `met` 또는 `review`다. 지침 조건(R01~)과 같은 모양이라 그대로 그리면 된다.
- **조건 이름과 개수를 프론트에 하드코딩하지 않는다.** 위밋 기준은 다를 수 있으니 항상 응답 `checks[]`를 그대로 그린다.

### PATCH `/submissions/{id}/checks/{check_id}` — 담당자가 항목 결과 수정

```json
// 요청
{ "result": "met", "note": "서명 원본 확인함" }
// 되돌리기
{ "result": null }
// 응답 200: 네 필드가 항상 온다
{ "verdict": "pass", "check": { ...수정된 check... }, "reply": { ...현재 초안... }, "reply_regenerated": true, "updated_at": "…" }
```
- 바꿀 수 있는 항목: `result`가 `met`·`unmet`·**`review`**인 항목. AI 확인필요를 담당자가 판단하는 게 핵심이다. `excluded`는 바꿀 수 없다(버튼 숨김, 요청 시 `409 CHECK_EXCLUDED`).
- `reply_regenerated: true`: 서버가 초안을 새로 만들었다. `reply`로 화면을 바꾼다.
- 담당자가 초안을 직접 고친 상태(`edited_by_manager=true`)면 서버는 초안을 덮어쓰지 않고 `reply_regenerated: false`를 준다(`reply`는 그대로인 현재 초안). 프론트는 "항목이 바뀌었습니다. 초안을 다시 만들까요?" 버튼을 띄우고, 누르면 `POST /submissions/{id}/reply/regenerate`를 부른다(P1).

### PUT `/submissions/{id}/reply` — 초안 저장

```json
{ "subject": "...", "body": "..." }
```
`409 REPLY_LOCKED` — 이미 `sending`이거나 `sent`인 경우.

### POST `/submissions/{id}/reply/mark-sent` — 담당자가 웹메일로 보냈음 표시 (잠정)

요청 본문은 없다. 응답은 `200 { "reply_status": "sent", "review_status": "confirmed" }`이다. 오류: `409 REPLY_LOCKED`(이미 보냄 표시), `422 REPLY_EMPTY`. `reply`에는 `compose_url`(문자열)과 `compose_truncated`(boolean)가 추가된다.

### POST `/submissions/{id}/reply/send` — 전송 (보류: 서비스 직접 발송)

요청 본문은 없다. 응답은 `202 { "status": "sending" }`이다. **현재 구현은 보류라 항상 `503 MAIL_BRIDGE_DOWN`을 준다**(메시지: [웹메일에서 열기] 안내).

오류:
- `409 REPLY_LOCKED`
- `422 REPLY_EMPTY`
- `503 MAIL_BRIDGE_DOWN` — 메일 연동 장애. 메시지를 그대로 띄운다.

### POST `/submissions/{id}/confirm`

```json
{ "reply": "not_needed" }   // 회신 없이 확인완료
```
응답에는 갱신된 `review_status`와 `reply_status`가 온다.

### PATCH `/submissions/{id}`

```json
{ "team_id": "t_club_007" }
{ "program": "aim", "team_id": "t_aim_002" }   // 프로그램 미확정 건 지정
{ "review_status": "pending" }                  // 확인완료 되돌리기 (P1)
```
- 확인완료를 되돌려도 **회신 상태는 바꾸지 않는다**(이미 `sent`면 그대로).
- 동시 수정은 **마지막 저장이 이긴다.** 응답의 `updated_at`을 보관해 두면 나중에 충돌 검사를 붙일 수 있다.
팀이 바뀌면 일부 조건(제출 이력 관련)을 서버가 다시 계산할 수 있다. 응답은 상세 전체다.

### POST `/submissions/{id}/rerun`
응답은 `202 { "processing_status": "queued" }`이다.

### GET `/teams/{team_id}`

```json
{
  "id": "t_club_007", "program": "club", "name": "코딩하는감자들",
  "aliases": ["코딩감자", "감자들"],
  "known_senders": ["student@example.ac.kr"],
  "submissions": [ { "id": "...", "received_at": "...", "meeting_date": "...", "total_amount": 64000, "verdict": "pass", "reply_status": "sent" } ]
}
```

### PUT `/teams/{team_id}/aliases`

```json
{ "aliases": ["코딩감자", "감자들"] }
```

### GET `/programs/{program}/rules`

```json
{
  "id": "rs_club_v1", "program": "club", "version": 1, "status": "confirmed",
  "confirmed_by": "동아리 담당자", "confirmed_at": "2026-10-28T11:00:00+09:00",
  "conditions": [
    { "id": "R08", "name": "1인당 20,000원 이내", "by": "code", "severity": "reject", "params": { "limit": 20000 }, "source": "1인당 2만원 이내", "enabled": true },
    { "id": "R18", "name": "1회/1일 사용", "enabled": false, "excluded_reason": "담당자 의견: 서류로 판단 안 함" }
  ]
}
```
- `note`(문자열 또는 null): 그 프로그램의 확정 기준이 없어 동아리 기준을 임시로 쓸 때 안내 문구가 온다. 지금은 위밋·캡스톤·AIM·해커톤이 이 경우다.

---

## 5. 현재 동아리 기준 조건 목록 (참고용, 하드코딩 금지)

| ID | 조건 | 판정 주체 | 미충족 시 |
|---|---|---|---|
| R01 | 영수증 첨부, 금액 > 0 | 코드 | 보완필요 |
| R02 | 연구비카드 매출전표 (간이·현금영수증 불가) | 코드 | 부적합 |
| R03 | 승인번호 표기 | 코드 | 보완필요 |
| R04 | 회의일 = 영수증 거래일 | 코드 | 부적합 |
| R05 | 평일 사용 (주말 불가) | 코드 | 부적합 |
| R06 | 20:00 이전 결제 | 코드 | 부적합 |
| R07 | 술집·주류 결제 불가 | AI | 부적합 |
| R08 | 1인당 20,000원 이내 | 코드 | 부적합 |
| R09 | 식비는 회의 후 / 다과비는 회의 전 정해진 시간 안에 결제 | AI+코드 | 부적합 |
| R10 | 회의 60분 이상 운영 | 코드 | 부적합 |
| R11 | 가맹점 광주광역시 북구 | 코드 | 부적합 |
| R12 | 회의 장소 카페·식당 불가 | AI | 부적합 |
| R13 | 회의내용 구체적·상세 | AI | 보완필요 |
| R14 | 참석자 전원 서명 (워드 작성 불가) | 추출+코드 | 보완필요 |
| R15 | 사용 비용 칸 = 영수증 합계 | 코드 | 보완필요 |
| R16 | 결제자 소속·이름·서명 | 추출+코드 | 보완필요 |
| R17 | 사용일로부터 7일째 18:00 전 제출 | 코드(접수 일시) | 보완필요 |
| R18~R20 | 1회/1일, 수업시간, 카드 예약 | — | 제외(`excluded`) |

위밋 기준은 아직 받지 못했다. 받으면 다른 조건 세트로 온다.

---

## 6. 화면 상태별 처리 체크리스트

| 상황 | 화면 |
|---|---|
| 목록 비어 있음 | "아직 접수된 증빙이 없습니다" |
| `queued`/`processing` | 행에 스피너와 "검수 중". 상세를 열면 원본은 보이고, 결과 영역은 스켈레톤 |
| `failed` | 빨간 안내와 `processing_error` 메시지, [다시 검수] 버튼. 원본 보기는 정상 |
| 팀 미확정 | 헤더에 "팀 미확정" 경고와 [팀 지정] |
| 쪽 이미지 로딩 실패 | "미리보기를 만들 수 없습니다"와 [원본 다운로드] |
| `sending` | 전송 버튼 자리에 "전송 중… (1~5분)" |
| `failed`(회신) | `reply.error` 메시지와 [다시 전송] |
| 401 | 로그인으로 이동 |
| 403 | "이 프로그램을 볼 권한이 없습니다" |

## 7. 개인정보 화면 규칙

- 학번은 서버가 가운데를 가려서 준다(`2023****`). 카드번호도 서버가 마스킹한다.
- 원본 이미지에는 가림 처리가 없다(담당자 검토용). 화면 캡처나 공유 기능은 넣지 않는다.
- 콘솔 로그에 응답 본문을 남기지 않는다.

## 8. 개발 방법 (백엔드 준비 전)

1. 아래 목 데이터로 화면을 먼저 만든다(MSW나 JSON 파일).
2. 백엔드가 올라오면 `http://localhost:8000/docs`의 스키마로 타입을 다시 맞춘다. `openapi-typescript`로 타입을 자동 생성하는 것을 추천한다.
3. CORS: 백엔드가 `http://localhost:5173`, `http://localhost:3000`을 허용한다. 다른 포트를 쓰면 알려 준다.

### TypeScript 타입 (요약)

```ts
type Program = "club" | "aim" | "hackathon" | "wemeet" | "capstone";
type ProcessingStatus = "queued" | "processing" | "done" | "failed";
type Verdict = "pass" | "needs_fix" | "reject" | "review";
type ReviewStatus = "pending" | "confirmed";
type ReplyStatus = "none" | "draft" | "sending" | "sent" | "failed" | "not_needed";
type CheckResult = "met" | "unmet" | "review" | "excluded";
type CheckBy = "code" | "ai" | "extract+code";

interface TeamRef { id: string | null; name: string }

interface SubmissionListItem {
  id: string; program: Program; team: TeamRef;
  received_at: string; sender: { name: string; email: string }; subject: string;
  processing_status: ProcessingStatus; verdict: Verdict | null;
  review_status: ReviewStatus; reply_status: ReplyStatus;
  summary: { meeting_date: string | null; total_amount: number | null; attendee_count: number | null;
             failed_checks: string[]; review_checks: string[]; failed_count: number; review_count: number } | null;
}

interface PageImage { n: number; url: string; width: number; height: number }  // url = 서명 URL
interface Attachment { file_id: string; name: string; kind: "minutes" | "receipt" | "other";
  format: string; page_count: number; size: number; pages: PageImage[]; download_url: string }

interface Evidence { field: string | null; found: string | null; expected: string | null;
  file_id: string | null; page: number | null; bbox: [number, number, number, number] | null;
  rule_source: string | null;
  alternatives?: { label: string; result: "met" | "unmet"; detail: string; expected: string | null }[] | null }

interface Check { check_id: string; name: string; by: CheckBy; severity: "reject" | "needs_fix";
  result: CheckResult; ai_result: CheckResult; overridden: boolean; message: string;
  evidence: Evidence; manager_note: string | null }

interface Reply { status: ReplyStatus; to: string; subject: string; body: string;
  internal_notes: string[]; edited_by_manager: boolean; sent_at: string | null; error: string | null }
```

### 목 데이터에 꼭 넣을 케이스

| # | 케이스 | 확인할 화면 |
|---|---|---|
| 1 | 적합, 회신 없이 확인완료 | 초록 배지, [확인완료만] |
| 2 | 보완필요 (서명 1명 누락) | 주황, 초안에 서명 항목 |
| 3 | 부적합 (20:30 결제 + 주말) | 빨강, 항목 2개 |
| 4 | AI 확인필요 (다과비/식비 애매) | 회색, internal_notes |
| 5 | 검수 중 | 스피너, 자동 새로고침 |
| 6 | 처리 실패 | 오류와 [다시 검수] |
| 7 | 팀 미확정 | 사이드바 "팀 미확정", [팀 지정] |
| 8 | 전송 중 → 전송 완료 | 버튼 잠금 |
| 9 | 같은 팀 재제출 | previous_submissions 링크 |

---

## 9. 아직 정해지지 않은 것 (프론트 영향 있음)

| 항목 | 영향 | 지금 가정 |
|---|---|---|
| 로그인 방식 | S0 | 아이디·비밀번호(우리가 발급). 학교 계정 로그인은 안 함 |
| 위밋 기준 | S2 조건 목록 | 응답 그대로 그리면 영향 없음 |
| 배포 주소 | API base URL | 환경변수 `VITE_API_BASE` 등으로 분리 |
| 실시간 갱신 | 목록 | 폴링(15/60초). 필요하면 나중에 SSE |
| 담당자 항목 수정 범위 | S2 | 결과(충족/미충족)와 메모만 |

질문은 백엔드 담당에게 하고, 답이 나오면 이 문서에 반영한다.

---

## 부록 A. 프론트 설계(FE_PLAN v0.2) 8장 질문 답변 — 2026-10-30

| # | 질문 | 답 |
|---|---|---|
| 1 | 쪽 이미지·다운로드 인증 | **서명 URL.** `attachments[].pages[].url`, `download_url`을 그대로 `<img src>`·링크에 쓴다. 30분 만료, 상세 재조회 시 갱신. blob 우회는 필요 없다 |
| 2 | 목록 정렬 | **서버 정렬.** `sort=default`(처리 실패 → 미확인[부적합→보완필요→AI 확인필요→적합→검수 중] → 확인완료, 그룹 안 최신순), `received_desc`, `received_asc` |
| 3 | PATCH checks의 `reply_regenerated` | **항상 온다.** `verdict`, `check`, `reply`(현재 초안), `reply_regenerated`, `updated_at` |
| 4 | 상세 `reply_status` vs `reply.status` | 같은 값이다. 상세에도 최상위 `reply_status`를 넣는다 |
| 5 | `review` 항목 수정 / `excluded` | `met`·`unmet`·`review` 모두 [충족으로]/[미충족으로] 가능. `excluded`는 불가(숨김). 되돌리기는 `{"result": null}` |
| 6 | 확인완료 되돌리기 | `PATCH /submissions/{id}` `{"review_status":"pending"}` (P1). 회신 상태는 안 바뀐다 |
| 7 | 관리자 `programs`·`role` | `role: "admin"`, programs 5개 전부. 담당자는 계정 2개(위 "계정과 권한") |
| 8 | 동시 수정 | 마지막 저장이 이긴다. 담당자끼리는 프로그램이 달라 겹치지 않는다. `updated_at` 제공 |
| 9 | 쪽 이미지 크기·bbox | 150dpi PNG, `pages[].width/height` 제공. `bbox`는 0~1 비율 `[x0,y0,x1,y1]`, 왼쪽 위 원점 |
| 10 | `failed_checks`에 확인필요 포함? | 미충족만. 확인필요는 `summary.review_checks`로 따로 준다 |

**함께 바뀐 것 (8장 외)**
- 계정 2개 · 프로그램 5개 (`club`, `aim`, `hackathon`, `wemeet`, `capstone`)
- 회신은 잠정적으로 "웹메일에서 열기 + 초안 복사 + 보냈음 표시"다. 서비스 직접 발송은 보류다. 전송 버튼 영역을 바꿀 수 있게 만든다
- 프론트 라우팅 `/:program/...`은 그대로 좋다. 프로그램 값만 5개로 늘었다

