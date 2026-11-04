// S1 목록: 요약 카드 · 팀 사이드바 · 제출 목록 (서버 정렬)
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, PROGRAM_NAMES, qs, type Page, type Program, type SubmissionListItem, type Summary, type TeamListItem } from "../api";
import { fmtDate, fmtDateTime, ReplyLabel, ReviewBadge, Spinner, VerdictBadge, won } from "../ui";

type Card = { key: keyof Summary; label: string; tone: string; filter: Record<string, string> };
const CARDS: Card[] = [
  { key: "today_received", label: "오늘 접수", tone: "", filter: { from: "today" } },
  { key: "unconfirmed", label: "담당자 미확인", tone: "blue", filter: { review_status: "pending" } },
  { key: "ai_review", label: "AI 확인필요", tone: "purple", filter: { verdict: "review", review_status: "pending" } },
  { key: "needs_fix", label: "보완필요", tone: "orange", filter: { verdict: "needs_fix", review_status: "pending" } },
  { key: "reject", label: "부적합", tone: "red", filter: { verdict: "reject", review_status: "pending" } },
  { key: "reply_failed", label: "전송 실패", tone: "red", filter: { reply_status: "failed" } },
];
const FILTER_KEYS = ["team_id", "verdict", "review_status", "reply_status", "from", "to", "q"];

function today() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function ListPage({ program: fixed }: { program?: "unassigned" }) {
  const params = useParams();
  const program = (fixed ?? params.program) as Program | "unassigned";
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const [teamSearch, setTeamSearch] = useState("");
  const f = Object.fromEntries(FILTER_KEYS.map((k) => [k, sp.get(k) ?? ""]));
  const page = Number(sp.get("page") ?? 1);
  const sort = sp.get("sort") ?? "received_desc"; // 기본: 최근에 받은 순 (담당자 요청 2026-11-02)

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(sp);
    for (const [k, v] of Object.entries(patch)) v ? next.set(k, v) : next.delete(k);
    if (!("page" in patch)) next.delete("page");
    setSp(next, { replace: true });
  };

  const list = useQuery({
    queryKey: ["list", program, f, page, sort],
    queryFn: () => api<Page<SubmissionListItem>>(`/programs/${program}/submissions${qs({ ...f, sort, page, size: 50 })}`),
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.processing_status === "queued" || i.processing_status === "processing") ? 15_000 : 60_000),
  });
  const summary = useQuery({ queryKey: ["summary", program], queryFn: () => api<Summary>(`/programs/${program}/summary`), refetchInterval: 30_000 });
  const teams = useQuery({
    queryKey: ["teams", program],
    queryFn: () => api<TeamListItem[]>(`/programs/${program}/teams`),
    enabled: program !== "unassigned",
    refetchInterval: 60_000,
  });

  const shownTeams = useMemo(() => {
    const all = teams.data ?? [];
    const k = teamSearch.trim().toLowerCase();
    return k ? all.filter((t) => t.name.toLowerCase().includes(k)) : all;
  }, [teams.data, teamSearch]);
  const totalCount = (teams.data ?? []).reduce((a, t) => a + t.total, 0);
  const totalUnconfirmed = (teams.data ?? []).reduce((a, t) => a + t.unconfirmed, 0);
  const anyFilter = FILTER_KEYS.some((k) => f[k]);
  const processing = summary.data?.processing ?? 0;
  const title = program === "unassigned" ? "프로그램 미확정" : `${PROGRAM_NAMES[program]} 증빙`;

  return (
    <div className={program === "unassigned" ? "list-layout single" : "list-layout"}>
      {program !== "unassigned" && (
        <aside className="sidebar">
          <input className="search" placeholder="⌕ 팀 검색" value={teamSearch} onChange={(e) => setTeamSearch(e.target.value)} />
          <button className={`team-row ${!f.team_id ? "active" : ""}`} onClick={() => set({ team_id: null })}>
            <span>전체</span><span className="pill">{totalUnconfirmed || totalCount}</span>
          </button>
          <div className="team-list">
            {teams.isLoading && <div className="muted small pad"><Spinner /> 불러오는 중…</div>}
            {shownTeams.map((t) => {
              const id = t.id ?? "unassigned";
              return (
                <button key={id} className={`team-row ${f.team_id === id ? "active" : ""} ${t.id === null ? "unassigned" : ""}`}
                  title={t.name} onClick={() => set({ team_id: id })}>
                  <span className="ellipsis">{t.name}</span>
                  <span className={t.unconfirmed ? "pill blue" : "pill zero"}>{t.unconfirmed}</span>
                </button>
              );
            })}
          </div>
        </aside>
      )}

      <main className="list-main">
        <div className="page-head">
          <h1>{title}</h1>
          <p className="muted xsmall">
            {processing ? <><Spinner /> 검수 중 {processing}건 · 15초마다 자동 새로고침</> : "60초마다 자동 새로고침"}
            {list.isFetching && " · 갱신 중"}
          </p>
        </div>
        {program === "unassigned" && (
          <div className="alert yellow">서버가 프로그램을 정하지 못한 제출입니다(예: AIM·해커톤에 모두 있는 팀). 상세에서 프로그램과 팀을 지정해 주세요.</div>
        )}

        <div className="cards">
          {CARDS.map((c) => {
            const active = Object.entries(c.filter).every(([k, v]) => (v === "today" ? f[k] === today() : f[k] === v));
            const n = summary.data?.[c.key];
            return (
              <button key={c.key} className={`card ${active ? "active" : ""}`}
                onClick={() => (active ? set(Object.fromEntries(FILTER_KEYS.map((k) => [k, null]))) :
                  set({ ...Object.fromEntries(FILTER_KEYS.map((k) => [k, null])), ...Object.fromEntries(Object.entries(c.filter).map(([k, v]) => [k, v === "today" ? today() : v])) }))}>
                <span className="card-label">{c.label}</span>
                <span className={`card-num ${n ? c.tone : "zero"}`}>{n ?? <span className="skeleton" />}</span>
              </button>
            );
          })}
        </div>

        <div className="filters">
          <input className="search wide" placeholder="⌕ 팀명, 보낸 사람, 제목" defaultValue={f.q}
            onKeyDown={(e) => e.key === "Enter" && set({ q: (e.target as HTMLInputElement).value })} />
          <select value={sort} onChange={(e) => set({ sort: e.target.value === "received_desc" ? null : e.target.value })} title="정렬">
            <option value="received_desc">정렬: 날짜순 (최근 먼저)</option><option value="received_asc">정렬: 날짜순 (오래된 먼저)</option>
            <option value="default">정렬: 해결할 것 먼저</option>
          </select>
          <select value={f.reply_status} onChange={(e) => set({ reply_status: e.target.value })} className={f.reply_status ? "on" : ""}>
            <option value="">회신</option><option value="draft">초안</option><option value="sent">보냄</option>
            <option value="failed">전송 실패</option><option value="not_needed">회신 안 함</option>
          </select>
          <input type="date" value={f.from} onChange={(e) => set({ from: e.target.value })} title="접수일 부터" />
          <input type="date" value={f.to} onChange={(e) => set({ to: e.target.value })} title="접수일 까지" />
          {anyFilter && <button className="link" onClick={() => set(Object.fromEntries(FILTER_KEYS.map((k) => [k, null])))}>필터 초기화</button>}
        </div>

        <table className="table">
          <thead>
            <tr>
              <th>접수</th><th>팀</th><th>회의일</th><th className="num">금액</th><th>AI 판정</th><th>걸린 항목</th><th>담당자</th><th>회신</th>
            </tr>
          </thead>
          <tbody>
            {list.isLoading && <tr><td colSpan={8} className="muted center"><Spinner /> 불러오는 중…</td></tr>}
            {list.data?.items.length === 0 && <tr><td colSpan={8} className="muted center pad">아직 접수된 증빙이 없습니다</td></tr>}
            {list.data?.items.map((s) => (
              <tr key={s.id} onClick={() => nav(`/submissions/${s.id}`)} className={s.review_status === "confirmed" ? "dim" : ""}>
                <td className="nowrap">{fmtDateTime(s.received_at)}</td>
                <td>{s.team.id ? <span className="strong">{s.team.name}</span> : <span className="badge orange outline">팀 미확정</span>}</td>
                <td>{fmtDate(s.summary?.meeting_date)}</td>
                <td className="num">{won(s.summary?.total_amount)}</td>
                <td><VerdictBadge verdict={s.verdict} status={s.processing_status} /></td>
                <td>
                  {s.summary?.failed_checks.slice(0, 2).map((c) => <span key={c} className="tag">{c.replace(/ \(.*\)$/, "")}</span>)}
                  {(s.summary?.failed_count ?? 0) > 2 && <span className="muted xsmall"> 외 {(s.summary?.failed_count ?? 0) - 2}</span>}
                  {!s.summary?.failed_count && (s.summary?.review_count ?? 0) > 0 && <span className="muted xsmall">확인필요 {s.summary?.review_count}</span>}
                </td>
                <td><ReviewBadge status={s.review_status} /></td>
                <td><ReplyLabel status={s.reply_status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        {list.data && list.data.total > list.data.size && (
          <div className="pager">
            <button className="ghost small" disabled={page <= 1} onClick={() => set({ page: String(page - 1) })}>‹ 이전</button>
            <span className="muted small">{page} / {Math.ceil(list.data.total / list.data.size)}</span>
            <button className="ghost small" disabled={page * list.data.size >= list.data.total} onClick={() => set({ page: String(page + 1) })}>다음 ›</button>
          </div>
        )}
        {list.data && <p className="muted xsmall">전체 {list.data.total}건 · 정렬: {sort === "default" ? "처리 실패 → 미확인(부적합 → 보완필요 → AI 확인필요 → 적합 → 검수 중) → 확인완료" : sort === "received_asc" ? "날짜순 (오래된 먼저)" : "날짜순 (최근 먼저)"}</p>}
      </main>
    </div>
  );
}
