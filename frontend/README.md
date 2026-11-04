# meeting-fee-review-agent-front

회의비 증빙 자동 검수 Agent — 담당자 화면(프론트엔드). 백엔드·결정 문서는 팀 비공개 레포 `upstage-cnu-7team/meeting-fee-review-agent-back`에 있다.

- 문서: [API 약속 (공개용 사본)](docs/frontend-api.md)

- Vite + React 19 + TanStack Query
- 개발: `npm install && npm run dev` (http://localhost:5173, `/api`는 localhost:8000으로 프록시)
- 배포: Vercel. `/api/*`는 `vercel.json`에서 `https://api.jnuai-meetingfee.com`으로 넘긴다.
