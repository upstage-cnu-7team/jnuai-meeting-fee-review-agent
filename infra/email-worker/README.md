# Email Worker: submit@ → 백엔드 웹훅

```
학생 → 담당자 OWA → 종희 M365 → Power Automate → submit@jnuai-meetingfee.com
   → Cloudflare Email Routing → 이 Worker ─┬─ 원본(raw MIME) POST → https://api.jnuai-meetingfee.com/api/intake/mail (X-Intake-Secret)
                                            └─ 백업 전달 → Gmail (BACKUP_TO)
api.jnuai-meetingfee.com → Cloudflare Tunnel → 백엔드(지금: 종희 맥 localhost:8000, 나중: 배포 서버)
```

## 처음 한 번
1. `cloudflared tunnel login` (브라우저에서 jnuai-meetingfee.com 승인)
2. `cloudflared tunnel create meetingfee` → `cloudflared tunnel route dns meetingfee api.jnuai-meetingfee.com`
3. `npx wrangler@4 login` → `wrangler.toml`의 `BACKUP_TO` 채우기 → `npx wrangler@4 deploy`
4. 비밀 키(백엔드 `.env`의 `INTAKE_SECRET`과 같은 값):
   `grep '^INTAKE_SECRET=' ../../backend/.env | cut -d= -f2- | npx wrangler@4 secret put INTAKE_SECRET`
5. Cloudflare 대시보드 → Email → Email Routing → 라우팅 규칙 → `submit@` 동작을 **Worker로 보내기 → meetingfee-intake**로 바꾸기

## 평소
- 터널 켜기: `cloudflared tunnel run --url http://localhost:8000 meetingfee`
- 백엔드 켜기: `cd backend && uv run uvicorn app.main:app --port 8000`
- Worker 로그: `npx wrangler@4 tail`
