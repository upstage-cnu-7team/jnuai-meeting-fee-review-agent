// S2 제출 상세: 왼쪽 원본(쪽 이미지), 오른쪽 추출 요약 · 조건별 결과 · 회신 초안
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMe } from "../App";
import {
  api, ApiError, PROGRAM_NAMES, qs, type Attachment, type Check, type CheckPatchResponse, type Page, type Program,
  type Reply, type SubmissionDetail, type SubmissionListItem, type TeamListItem,
} from "../api";
import { BY_LABEL, fmtDateTime, ResultIcon, ReviewBadge, Spinner, VERDICT, VerdictBadge, won } from "../ui";

const KIND_LABEL = { minutes: "회의록", receipt: "영수증", other: "기타" };

export default function DetailPage() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const key = ["detail", id];
  const d = useQuery({
    queryKey: key,
    queryFn: () => api<SubmissionDetail>(`/submissions/${id}`),
    refetchInterval: (q) => (q.state.data && ["queued", "processing"].includes(q.state.data.processing_status) ? 5_000 : false),
  });
  const [focus, setFocus] = useState<{ file_id: string | null; page: number | null; at: number } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const flash = (m: string) => { setToast(m); setTimeout(() => setToast(null), 2500); };
  const invalidateLists = () => {
    qc.invalidateQueries({ queryKey: ["list"] });
    qc.invalidateQueries({ queryKey: ["summary"] });
    qc.invalidateQueries({ queryKey: ["teams"] });
    qc.invalidateQueries({ queryKey: ["unassigned-count"] });
  };

  if (d.isLoading) return <div className="center-fill"><Spinner /> 불러오는 중…</div>;
  if (d.error) {
    const e = d.error as ApiError;
    return <div className="center-fill"><div className="alert red">{e.status === 403 ? "이 제출 건을 볼 권한이 없습니다." : e.message}</div></div>;
  }
  const s = d.data!;
  const setDetail = (patch: Partial<SubmissionDetail>) => qc.setQueryData<SubmissionDetail>(key, (old) => (old ? { ...old, ...patch } : old));
  const backTo = s.program ? `/${s.program}` : "/unassigned";

  return (
    <div className="detail">
      <Header s={s} backTo={backTo} onChanged={(nd) => { qc.setQueryData(key, nd); invalidateLists(); }}
        onRerun={async () => {
          await api(`/submissions/${s.id}/rerun`, { method: "POST" });
          setDetail({ processing_status: "queued" });
          invalidateLists();
        }} />
      <div className="split">
        <Viewer attachments={s.attachments} focus={focus} />
        <div className="result-pane">
          {s.processing_status === "failed" && (
            <div className="alert red">
              <b>처리 실패</b> · {s.processing_error ?? "검수 중 오류가 발생했습니다."}<br />
              원본은 왼쪽에서 볼 수 있습니다. [다시 검수]로 재시도하세요.
            </div>
          )}
          {["queued", "processing"].includes(s.processing_status) && (
            <div className="alert gray"><Spinner /> AI가 검수 중입니다 (1건에 20~60초). 끝나면 자동으로 바뀝니다.</div>
          )}
          {s.processing_status === "done" && (
            <>
              <ExtractedSummary s={s} />
              <Checks s={s} onFocus={(f) => setFocus({ ...f, at: Date.now() })}
                onPatched={(r) => {
                  qc.setQueryData<SubmissionDetail>(key, (old) => old && ({
                    ...old, verdict: r.verdict, reply: r.reply, reply_status: r.reply.status, updated_at: r.updated_at,
                    checks: old.checks.map((c) => (c.check_id === r.check.check_id ? r.check : c)),
                  }));
                  invalidateLists();
                  if (!r.reply_regenerated && r.reply.status !== "sent") flash("항목이 바뀌었습니다. 직접 고친 초안은 그대로 두었습니다.");
                }} />
            </>
          )}
          {s.processing_status === "done" && (
            <ReplyEditor s={s} onReply={(reply) => setDetail({ reply, reply_status: reply.status })}
              onStatus={(rs, rv) => { setDetail({ reply_status: rs, review_status: rv, reply: { ...s.reply, status: rs } }); invalidateLists(); }}
              onNext={async () => {
                const prog = s.program ?? "unassigned";
                const l = await api<Page<SubmissionListItem>>(`/programs/${prog}/submissions${qs({ review_status: "pending", size: 5 })}`);
                const next = l.items.find((i) => i.id !== s.id && i.processing_status === "done");
                next ? nav(`/submissions/${next.id}`) : (flash("미확인 건이 더 없습니다."), nav(backTo));
              }}
              flash={flash} />
          )}
        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

function Header({ s, backTo, onChanged, onRerun }: {
  s: SubmissionDetail; backTo: string; onChanged: (d: SubmissionDetail) => void; onRerun: () => void;
}) {
  const me = useMe().data;
  const [picking, setPicking] = useState(false);
  const [program, setProgram] = useState<Program | "">(s.program ?? "");
  const teams = useQuery({
    queryKey: ["teams", program],
    queryFn: () => api<TeamListItem[]>(`/programs/${program}/teams`),
    enabled: picking && !!program,
  });
  const patch = useMutation({
    mutationFn: (body: object) => api<SubmissionDetail>(`/submissions/${s.id}`, { method: "PATCH", json: body }),
    onSuccess: (nd) => { onChanged(nd); setPicking(false); },
  });
  const alert = s.reply.internal_notes.find((n) => n.includes("지정해 주세요") || n.includes("임시 판정"));
  return (
    <div className="detail-head">
      <div className="row gap">
        <Link to={backTo} className="ghost small">← 목록</Link>
        <h2>{s.team.id ? s.team.name : <span className="badge orange outline">팀 미확정</span>}</h2>
        {s.program ? <span className="badge gray">{PROGRAM_NAMES[s.program]}</span> : <span className="badge orange">프로그램 미확정</span>}
        <button className="ghost small" onClick={() => setPicking((v) => !v)}>{s.program ? "팀 변경" : "프로그램·팀 지정"}</button>
        {s.processing_status === "done" && s.verdict && <span className={`badge ${VERDICT[s.verdict].tone}`}>AI 판정: {VERDICT[s.verdict].label}</span>}
        {s.processing_status !== "done" && <VerdictBadge verdict={null} status={s.processing_status} />}
        <ReviewBadge status={s.review_status} />
        {s.review_status === "confirmed" && (
          <button className="link xsmall" onClick={() => patch.mutate({ review_status: "pending" })}>확인 되돌리기</button>
        )}
        <div className="spacer" />
        {s.rule_set && <span className="muted xsmall">기준: {PROGRAM_NAMES[(s.rule_set.id.split("_")[1] as Program)] ?? ""} v{s.rule_set.version}</span>}
        <button className="ghost small" onClick={onRerun} disabled={["queued", "processing"].includes(s.processing_status)}>↻ 다시 검수</button>
      </div>
      <div className="row gap muted xsmall wrap">
        <span>접수 {fmtDateTime(s.received_at)}</span>
        <span>{s.sender.name} &lt;{s.sender.email}&gt;</span>
        <MailSubject s={s} />
        {s.previous_submissions.slice(0, 1).map((p) => (
          <Link key={p.id} to={`/submissions/${p.id}`} className="link">
            이전 제출 {fmtDateTime(p.received_at).split(" ")[0]} · {p.verdict ? VERDICT[p.verdict].label : "—"} →
          </Link>
        ))}
        {s.team.match_reason && <span title="팀을 정한 근거">· 팀 근거: {s.team.match_reason}</span>}
      </div>
      {alert && <div className="alert yellow small">{alert}</div>}
      {picking && (
        <div className="picker">
          {!s.program && (
            <select value={program} onChange={(e) => setProgram(e.target.value as Program)}>
              <option value="">프로그램 선택</option>
              {me?.programs.map((p) => <option key={p} value={p}>{PROGRAM_NAMES[p]}</option>)}
            </select>
          )}
          <select disabled={!program} defaultValue="" onChange={(e) => e.target.value &&
            patch.mutate(s.program ? { team_id: e.target.value } : { program, team_id: e.target.value })}>
            <option value="">{teams.isLoading ? "불러오는 중…" : "팀 선택"}</option>
            {teams.data?.filter((t) => t.id).map((t) => <option key={t.id} value={t.id!}>{t.name}</option>)}
          </select>
          {!s.program && program && <button className="ghost small" onClick={() => patch.mutate({ program })}>팀 없이 프로그램만 지정</button>}
          {patch.error && <span className="red-text small">{(patch.error as ApiError).message}</span>}
        </div>
      )}
    </div>
  );
}

function MailSubject({ s }: { s: SubmissionDetail }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="link xsmall" onClick={() => setOpen((v) => !v)}>{open ? "▾" : "▸"} {s.mail.subject || "(제목 없음)"}</button>
      {open && <pre className="mail-body">{s.mail.body_text || "(본문 없음)"}</pre>}
    </>
  );
}

function Viewer({ attachments, focus }: { attachments: Attachment[]; focus: { file_id: string | null; page: number | null; at: number } | null }) {
  const [tab, setTab] = useState(0);
  const [zoom, setZoom] = useState(0.5); // 처음에는 50%로 한 쪽 전체가 보이게
  const [fit, setFit] = useState(false);
  const [cur, setCur] = useState(1);
  const [hl, setHl] = useState<number | null>(null);
  const [broken, setBroken] = useState<Record<string, boolean>>({});
  const box = useRef<HTMLDivElement>(null);
  const a = attachments[tab];

  useEffect(() => {
    if (!focus) return;
    const i = attachments.findIndex((x) => x.file_id === focus.file_id);
    if (i >= 0) setTab(i);
    if (focus.page) {
      setTimeout(() => {
        box.current?.querySelector(`[data-page="${focus.page}"]`)?.scrollIntoView({ behavior: "smooth", block: "start" });
        setHl(focus.page);
        setTimeout(() => setHl(null), 1800);
      }, 50);
    }
  }, [focus, attachments]);

  if (!attachments.length) return <div className="viewer"><div className="center-fill muted">첨부 파일이 없습니다</div></div>;
  const onScroll = () => {
    const el = box.current;
    if (!el) return;
    const pages = Array.from(el.querySelectorAll<HTMLElement>("[data-page]"));
    const top = el.scrollTop + 40;
    const p = pages.filter((x) => x.offsetTop <= top).pop();
    if (p) setCur(Number(p.dataset.page));
  };
  return (
    <div className="viewer">
      <div className="att-tabs">
        {attachments.map((x, i) => (
          <button key={x.file_id} className={`att-tab ${i === tab ? "active" : ""}`} onClick={() => { setTab(i); setCur(1); }}>
            ▤ {x.name} <span className="muted xsmall">{KIND_LABEL[x.kind]} · {x.page_count}쪽</span>
          </button>
        ))}
      </div>
      <div className="viewer-bar">
        <span className="muted xsmall">{a.page_count ? `${cur} / ${a.page_count}쪽` : "—"}</span>
        <div className="spacer" />
        <button className="ghost small" onClick={() => { setFit(false); setZoom((z) => Math.max(0.25, z - 0.25)); }}>−</button>
        <span className="xsmall">{fit ? "폭 맞춤" : `${Math.round(zoom * 100)}%`}</span>
        <button className="ghost small" onClick={() => { setFit(false); setZoom((z) => Math.min(3, z + 0.25)); }}>+</button>
        <button className={`ghost small ${fit ? "on" : ""}`} onClick={() => setFit(true)}>폭 맞춤</button>
        <a className="ghost small" href={a.download_url}>⤓ 원본 다운로드</a>
      </div>
      {["hwp", "hwpx", "docx"].includes(a.format) && a.pages.length > 0 && (
        <div className="viewer-note">미리보기입니다. 원본 모양과 다를 수 있으니 정확한 모양은 원본 다운로드로 확인하세요.</div>
      )}
      <div className="pages" ref={box} onScroll={onScroll}>
        {a.pages.length === 0 && <div className="center-fill muted">미리보기를 만들 수 없습니다. <a className="link" href={a.download_url}>원본 다운로드</a></div>}
        {a.pages.map((p) => (
          <div key={p.n} data-page={p.n} className={`page ${hl === p.n ? "hl" : ""}`} style={fit ? undefined : { width: p.width * 0.6 * zoom }}>
            {broken[`${a.file_id}-${p.n}`]
              ? <div className="muted pad">미리보기를 불러오지 못했습니다. 화면을 새로고침해 주세요.</div>
              : <img src={p.url} width={p.width} height={p.height} alt={`${a.name} ${p.n}쪽`} loading="lazy"
                  onError={() => setBroken((b) => ({ ...b, [`${a.file_id}-${p.n}`]: true }))} />}
            <span className="page-no">{p.n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ExtractedSummary({ s }: { s: SubmissionDetail }) {
  const [more, setMore] = useState(false);
  const x = s.extracted;
  if (!x) return null;
  const r = x.receipt;
  const tx = r.transaction_datetime ? fmtDateTime(r.transaction_datetime).split(" ")[1] : "—";
  return (
    <section className="panel">
      <div className="panel-head"><h3>추출 요약</h3><button className="link xsmall" onClick={() => setMore((v) => !v)}>{more ? "접기 ▴" : "자세히 ▾"}</button></div>
      <dl className="kv">
        <dt>회의</dt><dd>{x.meeting_date ?? "—"} {x.start_time ?? ""}~{x.end_time ?? ""}</dd>
        <dt>장소</dt><dd>{x.place ?? "—"}</dd>
        <dt>금액</dt><dd>{won(r.total)}원 · {x.attendees.length}명</dd>
        <dt>결제</dt><dd>{tx} · {r.card_type ?? "—"}</dd>
      </dl>
      {more && (
        <div className="more">
          <dl className="kv">
            <dt>팀명</dt><dd>{x.team_name ?? "—"}</dd>
            <dt>회의명</dt><dd>{x.meeting_title ?? "—"}</dd>
            <dt>가맹점</dt><dd>{r.merchant_name ?? "—"}</dd>
            <dt>주소</dt><dd>{r.merchant_address ?? "—"}</dd>
            <dt>영수증</dt><dd>{r.type ?? "—"} · 승인 {r.approval_number || "없음"}</dd>
            <dt>카드</dt><dd>{r.card_number || "—"}</dd>
            <dt>사용 비용</dt><dd>{won(x.used_amount)}원</dd>
            <dt>결제자</dt><dd>{x.payer.affiliation} {x.payer.name} {x.payer.has_signature ? "✓" : "✗ 서명 없음"}</dd>
          </dl>
          <table className="mini">
            <thead><tr><th>소속</th><th>학번</th><th>이름</th><th>서명</th></tr></thead>
            <tbody>{x.attendees.map((a, i) => (
              <tr key={i}><td>{a.affiliation}</td><td>{a.student_id}</td><td>{a.name}</td><td>{a.has_signature ? "✓" : <span className="red-text">✗</span>}</td></tr>
            ))}</tbody>
          </table>
          {r.items.length > 0 && <p className="xsmall muted">품목: {r.items.map((i) => `${i.name} ${i.quantity}개 ${won(i.amount)}원`).join(", ")}</p>}
          {x.content && <pre className="content">{x.content}</pre>}
        </div>
      )}
    </section>
  );
}

const ORDER: Record<string, number> = { unmet: 0, review: 1, met: 2, excluded: 3 };

function Checks({ s, onFocus, onPatched }: {
  s: SubmissionDetail; onFocus: (f: { file_id: string | null; page: number | null }) => void; onPatched: (r: CheckPatchResponse) => void;
}) {
  const [showMet, setShowMet] = useState(false);
  const [showEx, setShowEx] = useState(false);
  const sorted = [...s.checks].sort((a, b) => ORDER[a.result] - ORDER[b.result] || a.check_id.localeCompare(b.check_id));
  const n = (r: string) => s.checks.filter((c) => c.result === r).length;
  const locked = s.reply_status === "sent" || s.reply_status === "sending";
  return (
    <section className="panel">
      <div className="panel-head">
        <h3>조건별 결과</h3>
        <div className="row gap-s">
          {n("unmet") > 0 && <span className="badge orange">미충족 {n("unmet")}</span>}
          {n("review") > 0 && <span className="badge purple">확인필요 {n("review")}</span>}
          <span className="badge green">충족 {n("met")}</span>
        </div>
      </div>
      {sorted.filter((c) => c.result === "unmet" || c.result === "review").map((c, i) => (
        <CheckRow key={c.check_id} c={c} sid={s.id} defaultOpen={i === 0} onFocus={onFocus} onPatched={onPatched} locked={locked} />
      ))}
      <button className="link xsmall" onClick={() => setShowMet((v) => !v)}>{showMet ? "▾" : "▸"} 충족 {n("met")}개 보기</button>
      {showMet && sorted.filter((c) => c.result === "met").map((c) => (
        <CheckRow key={c.check_id} c={c} sid={s.id} onFocus={onFocus} onPatched={onPatched} locked={locked} />
      ))}
      {n("excluded") > 0 && <button className="link xsmall right" onClick={() => setShowEx((v) => !v)}>제외 {n("excluded")}개 보기</button>}
      {showEx && sorted.filter((c) => c.result === "excluded").map((c) => (
        <div key={c.check_id} className="check excluded"><ResultIcon result="excluded" severity={c.severity} /><b>{c.check_id}</b> {c.name}<span className="muted xsmall"> · {c.message}</span></div>
      ))}
    </section>
  );
}

function CheckRow({ c, sid, defaultOpen, onFocus, onPatched, locked }: {
  c: Check; sid: string; defaultOpen?: boolean; locked: boolean;
  onFocus: (f: { file_id: string | null; page: number | null }) => void; onPatched: (r: CheckPatchResponse) => void;
}) {
  const [open, setOpen] = useState(!!defaultOpen);
  const [note, setNote] = useState(c.manager_note ?? "");
  const m = useMutation({
    mutationFn: (body: { result: "met" | "unmet" | null; note?: string | null }) =>
      api<CheckPatchResponse>(`/submissions/${sid}/checks/${c.check_id}`, { method: "PATCH", json: body }),
    onSuccess: onPatched,
  });
  const e = c.evidence;
  const where = e.page ? `${e.file_id ? "" : ""}p.${e.page}` : null;
  return (
    <div className={`check ${c.result}`}>
      <div className="check-head" onClick={() => setOpen((v) => !v)}>
        <ResultIcon result={c.result} severity={c.severity} />
        <div className="check-title">
          <div><b>{c.name}</b> <span className="by">{BY_LABEL[c.by]}</span>
            {c.overridden && <span className="badge blue xs">담당자 수정 · AI: {c.ai_result === "met" ? "충족" : c.ai_result === "unmet" ? "미충족" : "확인필요"}</span>}
            {c.result === "unmet" && <span className={`sev ${c.severity}`}>{c.severity === "reject" ? "부적합" : "보완필요"}</span>}
          </div>
          <div className="msg">{c.message}</div>
        </div>
        {where && <button className="link xsmall nowrap" onClick={(ev) => { ev.stopPropagation(); onFocus({ file_id: e.file_id, page: e.page }); }}>원본 {where}</button>}
        <span className="muted">{open ? "▴" : "▾"}</span>
      </div>
      {open && (
        <div className="check-body">
          {e.alternatives && e.alternatives.length > 0 && (
            <div className={`alts ${c.ai_result}`}>
              <div className="alts-head">
                {c.ai_result === "review" ? "두 방식으로 계산한 결과가 엇갈려 확인이 필요합니다" : "두 방식으로 모두 계산한 결과"}
              </div>
              {e.alternatives.map((a) => (
                <div key={a.label} className="alt">
                  <span className={`alt-result ${a.result}`}>{a.result === "met" ? "통과" : "위반"}</span>
                  <b>{a.label}</b>
                  <span className="muted">{a.detail}</span>
                  {a.expected && <span className="muted xsmall">기준: {a.expected}</span>}
                </div>
              ))}
              {c.ai_result === "review" && !locked && <div className="xsmall muted">맞는 쪽을 보고 아래 [충족으로]/[미충족으로]를 눌러 주세요.</div>}
            </div>
          )}
          <dl className="kv small">
            <dt>찾은 값</dt><dd>{e.found ?? "—"}</dd>
            <dt>기준</dt><dd>{e.expected ?? "—"}</dd>
            <dt>위치</dt><dd>{[where, e.field].filter(Boolean).join(" · ") || "—"}</dd>
            <dt>지침 원문</dt><dd>{e.rule_source ? `“${e.rule_source}”` : "—"}</dd>
          </dl>
          {!locked && (
            <div className="row gap-s">
              {c.result !== "met" && <button className="ghost small" disabled={m.isPending} onClick={() => m.mutate({ result: "met", note: note || null })}>충족으로 바꾸기</button>}
              {c.result !== "unmet" && <button className="ghost small" disabled={m.isPending} onClick={() => m.mutate({ result: "unmet", note: note || null })}>미충족으로 바꾸기</button>}
              {c.overridden && <button className="link xsmall" disabled={m.isPending} onClick={() => m.mutate({ result: null })}>AI 결과로 되돌리기</button>}
              <input className="note" placeholder="메모 (선택) — 예: 서명 원본 확인함" value={note} onChange={(ev) => setNote(ev.target.value)}
                onBlur={() => note !== (c.manager_note ?? "") && m.mutate({ result: c.overridden ? (c.result as "met" | "unmet") : null, note })} />
            </div>
          )}
          {m.error && <div className="red-text xsmall">{(m.error as ApiError).message}</div>}
        </div>
      )}
    </div>
  );
}

function ReplyEditor({ s, onReply, onStatus, onNext, flash }: {
  s: SubmissionDetail; onReply: (r: Reply) => void; onStatus: (rs: SubmissionDetail["reply_status"], rv: SubmissionDetail["review_status"]) => void;
  onNext: () => void; flash: (m: string) => void;
}) {
  const r = s.reply;
  const [subject, setSubject] = useState(r.subject);
  const [body, setBody] = useState(r.body);
  const [saved, setSaved] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [confirm, setConfirm] = useState(false);
  const locked = r.status === "sent" || r.status === "sending";
  const timer = useRef<number | undefined>(undefined);
  const dirty = useRef(false);

  // 서버 쪽 초안이 바뀌면(항목 수정으로 재생성) 편집기도 맞춘다
  useEffect(() => { if (!dirty.current) { setSubject(r.subject); setBody(r.body); } }, [r.subject, r.body]);

  const save = async (sub: string, b: string) => {
    setSaved("saving");
    try {
      const nr = await api<Reply>(`/submissions/${s.id}/reply`, { method: "PUT", json: { subject: sub, body: b } });
      dirty.current = false;
      onReply(nr);
      setSaved("saved");
    } catch { setSaved("error"); }
  };
  const edit = (sub: string, b: string) => {
    dirty.current = true;
    setSubject(sub); setBody(b); setSaved("idle");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => save(sub, b), 2000); // 입력 멈추고 2초 뒤 자동 저장
  };
  const flushSave = async () => { if (dirty.current) { window.clearTimeout(timer.current); await save(subject, body); } };

  const regenerate = async () => {
    const nr = await api<Reply>(`/submissions/${s.id}/reply/regenerate`, { method: "POST" });
    dirty.current = false; setSubject(nr.subject); setBody(nr.body); onReply(nr);
  };
  const markSent = async () => {
    await flushSave();
    try {
      const res = await api<{ reply_status: Reply["status"]; review_status: SubmissionDetail["review_status"] }>(`/submissions/${s.id}/reply/mark-sent`, { method: "POST" });
      onStatus(res.reply_status, res.review_status);
      setConfirm(false);
      flash("보냄으로 표시했습니다. 확인완료 처리됐습니다.");
    } catch (e) { flash((e as ApiError).message); }
  };
  const confirmOnly = async () => {
    const res = await api<{ reply_status: Reply["status"]; review_status: SubmissionDetail["review_status"] }>(`/submissions/${s.id}/confirm`, { method: "POST", json: { reply: "not_needed" } });
    onStatus(res.reply_status, res.review_status);
    flash("확인완료로 처리했습니다.");
  };
  const copy = async () => {
    await navigator.clipboard.writeText(`${subject}\n\n${body}`);
    flash("제목과 본문을 복사했습니다. 웹메일에 붙여 넣으세요.");
  };
  const unmet = s.checks.filter((c) => c.result === "unmet");
  const regenNeeded = r.edited_by_manager && !locked;

  return (
    <section className="panel reply">
      <div className="panel-head">
        <h3>회신 초안</h3>
        <span className="muted xsmall">
          {r.status === "sent" ? <span className="green-text">✓ 보냄</span> : saved === "saving" ? "저장 중…" : saved === "saved" ? "✓ 저장됨" : saved === "error" ? <span className="red-text">저장 실패</span> : "입력을 멈추고 2초 뒤 자동 저장"}
        </span>
      </div>
      {r.status === "sent" && <div className="alert green small">{fmtDateTime(r.sent_at)} 보냄 표시 · 확인완료 처리됨</div>}
      {r.status === "not_needed" && <div className="alert gray small">회신 없이 확인완료 처리됨</div>}
      <input className="readonly" value={`받는 사람 · ${r.to}`} readOnly />
      <input value={subject} disabled={locked} onChange={(e) => edit(e.target.value, body)} />
      <textarea value={body} disabled={locked} rows={11} onChange={(e) => edit(subject, e.target.value)} />
      {regenNeeded && <button className="link xsmall" onClick={regenerate}>↻ 직접 고친 초안입니다. 현재 항목 결과로 초안을 다시 만들기</button>}
      {r.internal_notes.length > 0 && (
        <div className="memo">
          <b>담당자 메모 · 학생에게 보내지 않음</b>
          {r.internal_notes.map((n, i) => <div key={i}>{n}</div>)}
        </div>
      )}
      <div className="reply-actions">
        {s.review_status === "confirmed" ? (
          <>
            <span className="muted xsmall">이 건은 확인완료입니다.</span>
            <div className="spacer" />
            <button className="primary" onClick={onNext}>다음 미확인 건 →</button>
          </>
        ) : (
          <>
            <button className="ghost" onClick={confirmOnly} title="적합이라 회신이 필요 없을 때">확인완료만</button>
            <div className="spacer" />
            <button className="ghost" onClick={copy}>초안 복사</button>
            {r.compose_url && (
              <a className="ghost btn" href={r.compose_url} target="_blank" rel="noreferrer" onClick={flushSave}
                title={r.compose_truncated ? "본문이 길어 앞부분만 채워집니다. 나머지는 [초안 복사]로 붙여 넣으세요" : "담당자 웹메일 새 메일 창"}>
                웹메일에서 열기{r.compose_truncated ? " (일부)" : ""} ↗
              </a>
            )}
            <button className="primary" onClick={() => setConfirm(true)} disabled={!body.trim()}>보냈음 표시</button>
          </>
        )}
      </div>
      {confirm && (
        <div className="modal-bg" onClick={() => setConfirm(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>웹메일로 보내셨나요?</h3>
            <p><b>{s.team.name}</b>({r.to})에게 회신을 보냈다고 표시합니다. 표시한 뒤에는 초안을 고칠 수 없고, 이 건은 확인완료가 됩니다.</p>
            <p className="muted xsmall">서비스는 실제 발송 여부를 알 수 없습니다. 웹메일에서 보낸 뒤 눌러 주세요.</p>
            {unmet.length > 0 && (
              <div className="box xsmall">현재 미충족 {unmet.length}건<br />{unmet.map((c, i) => <div key={c.check_id}>{i + 1}. {c.name}</div>)}</div>
            )}
            <div className="row gap-s right">
              <button className="ghost" onClick={() => setConfirm(false)}>취소</button>
              <button className="primary" onClick={markSent}>보냈음 표시</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
