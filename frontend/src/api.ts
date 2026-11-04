// 백엔드 API 타입과 호출. 기준: docs/frontend-api.md v0.2, 백엔드 /docs (OpenAPI)

export type Program = "club" | "aim" | "hackathon" | "wemeet" | "capstone";
export type ProcessingStatus = "queued" | "processing" | "done" | "failed";
export type Verdict = "pass" | "needs_fix" | "reject" | "review";
export type ReviewStatus = "pending" | "confirmed";
export type ReplyStatus = "none" | "draft" | "sending" | "sent" | "failed" | "not_needed";
export type CheckResult = "met" | "unmet" | "review" | "excluded";
export type CheckBy = "code" | "ai" | "extract+code";

export const PROGRAM_NAMES: Record<Program, string> = {
  club: "동아리", aim: "AIM챌린지", hackathon: "해커톤", wemeet: "위밋", capstone: "캡스톤",
};

export interface User { name: string; role: "manager" | "admin"; programs: Program[] }
export interface TeamRef { id: string | null; name: string }
export interface ListSummary {
  meeting_date: string | null; total_amount: number | null; attendee_count: number | null;
  failed_checks: string[]; review_checks: string[]; failed_count: number; review_count: number;
}
export interface SubmissionListItem {
  id: string; program: Program | null; team: TeamRef; received_at: string;
  sender: { name: string; email: string }; subject: string;
  processing_status: ProcessingStatus; verdict: Verdict | null;
  review_status: ReviewStatus; reply_status: ReplyStatus; summary: ListSummary | null;
}
export interface Page<T> { items: T[]; total: number; page: number; size: number }
export interface Summary {
  today_received: number; unconfirmed: number; ai_review: number; needs_fix: number;
  reject: number; reply_failed: number; processing: number;
}
export interface TeamListItem { id: string | null; name: string; unconfirmed: number; total: number; last_received_at: string | null }
export interface PageImage { n: number; url: string; width: number; height: number }
export interface Attachment {
  file_id: string; name: string; kind: "minutes" | "receipt" | "other"; format: string;
  page_count: number; size: number; pages: PageImage[]; download_url: string;
}
export interface Evidence {
  field: string | null; found: string | null; expected: string | null; file_id: string | null;
  page: number | null; bbox: number[] | null; rule_source: string | null;
  alternatives?: { label: string; result: "met" | "unmet"; detail: string; expected: string | null }[] | null;
}
export interface Check {
  check_id: string; name: string; by: CheckBy; severity: "reject" | "needs_fix"; result: CheckResult;
  ai_result: CheckResult; overridden: boolean; message: string; evidence: Evidence; manager_note: string | null;
}
export interface Reply {
  status: ReplyStatus; to: string; subject: string; body: string; internal_notes: string[];
  edited_by_manager: boolean; sent_at: string | null; error: string | null;
  compose_url: string | null; compose_truncated: boolean;
}
export interface Extracted {
  team_name: string | null; meeting_title: string | null; meeting_date: string | null;
  start_time: string | null; end_time: string | null; place: string | null; content: string | null;
  attendees: { affiliation: string | null; student_id: string; name: string | null; has_signature: boolean }[];
  writer_name: string | null; used_amount: number | null;
  payer: { affiliation: string | null; name: string | null; has_signature: boolean };
  receipt: {
    attached: boolean; type: string | null; merchant_name: string | null; merchant_address: string | null;
    card_type: string | null; card_number: string; approval_number: string; transaction_datetime: string | null;
    items: { name: string; quantity: number; amount: number }[]; total: number | null;
  };
}
export interface SubmissionDetail {
  id: string; program: Program | null;
  team: TeamRef & { match: "auto" | "manual" | "none"; match_reason: string | null };
  received_at: string; sender: { name: string; email: string }; mail: { subject: string; body_text: string };
  attachments: Attachment[]; processing_status: ProcessingStatus; processing_error: string | null;
  verdict: Verdict | null; review_status: ReviewStatus; reply_status: ReplyStatus; updated_at: string;
  rule_set: { id: string; version: number; confirmed_at: string | null } | null;
  extracted: Extracted | null; checks: Check[]; reply: Reply;
  previous_submissions: { id: string; received_at: string; verdict: Verdict | null; reply_status: ReplyStatus }[];
}
export interface CheckPatchResponse { verdict: Verdict | null; check: Check; reply: Reply; reply_regenerated: boolean; updated_at: string }
export interface Condition {
  id: string; name: string; by?: CheckBy | null; severity?: "reject" | "needs_fix" | null;
  params?: Record<string, unknown> | null; source?: string | null; enabled: boolean; excluded_reason?: string | null;
}
export interface RuleSet {
  id: string; program: Program; version: number; status: string; confirmed_by: string | null;
  confirmed_at: string | null; conditions: Condition[]; note: string | null;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) { super(message); }
}

const TOKEN_KEY = "mfr.token";
export const token = {
  get: () => sessionStorage.getItem(TOKEN_KEY),
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  const t = token.get();
  if (t) headers.Authorization = `Bearer ${t}`;
  let body = init.body;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  const res = await fetch(`/api${path}`, { ...init, headers, body });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    token.clear();
    window.location.assign("/login");
  }
  if (!res.ok) {
    let code = "HTTP_ERROR", message = "요청을 처리할 수 없습니다.";
    try {
      const e = await res.json();
      code = e.error?.code ?? code;
      message = e.error?.message ?? message;
    } catch { /* 본문 없음 */ }
    throw new ApiError(res.status, code, message);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

export function qs(params: Record<string, string | number | undefined | null>) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : "";
}
