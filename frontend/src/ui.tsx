// 공통 표시 요소: 배지, 날짜·금액 포맷, 빈/로딩 상태
import type { CheckBy, CheckResult, ProcessingStatus, ReplyStatus, ReviewStatus, Verdict } from "./api";

export const VERDICT: Record<Verdict, { label: string; tone: string }> = {
  pass: { label: "적합", tone: "green" },
  needs_fix: { label: "보완필요", tone: "orange" },
  reject: { label: "부적합", tone: "red" },
  review: { label: "AI 확인필요", tone: "purple" },
};

export function VerdictBadge({ verdict, status }: { verdict: Verdict | null; status: ProcessingStatus }) {
  if (status === "failed") return <span className="badge red outline">⊘ 처리 실패</span>;
  if (status !== "done") return <span className="badge gray"><Spinner /> 검수 중</span>;
  if (!verdict) return <span className="muted">—</span>;
  const v = VERDICT[verdict];
  return <span className={`badge ${v.tone}`}>{v.label}</span>;
}

export function ReviewBadge({ status }: { status: ReviewStatus }) {
  return status === "pending"
    ? <span className="dot-label blue">미확인</span>
    : <span className="dot-label done">✓ 확인완료</span>;
}

const REPLY: Record<ReplyStatus, { label: string; cls: string }> = {
  none: { label: "—", cls: "muted" },
  draft: { label: "✎ 초안", cls: "muted" },
  sending: { label: "◌ 전송 중", cls: "muted" },
  sent: { label: "✓ 보냄", cls: "green-text" },
  failed: { label: "⚠ 전송 실패", cls: "red-text" },
  not_needed: { label: "회신 안 함", cls: "muted" },
};

export function ReplyLabel({ status }: { status: ReplyStatus }) {
  const r = REPLY[status];
  return <span className={`small ${r.cls}`}>{r.label}</span>;
}

export const BY_LABEL: Record<CheckBy, string> = { code: "자동 계산", ai: "AI 판단", "extract+code": "자동 추출" };

export function ResultIcon({ result, severity }: { result: CheckResult; severity: "reject" | "needs_fix" }) {
  if (result === "met") return <span className="ricon green">✓</span>;
  if (result === "unmet") return <span className={`ricon ${severity === "reject" ? "red" : "orange"}`}>✕</span>;
  if (result === "review") return <span className="ricon purple">?</span>;
  return <span className="ricon gray">—</span>;
}

export function Spinner() {
  return <span className="spinner" aria-hidden />;
}

export function fmtDateTime(iso: string | null | undefined) {
  if (!iso) return "—";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function fmtDate(s: string | null | undefined) {
  if (!s) return "—";
  const [, m, d] = s.split("-");
  return `${Number(m)}/${Number(d)}`;
}

export const won = (n: number | null | undefined) => (n === null || n === undefined ? "—" : n.toLocaleString("ko-KR"));
