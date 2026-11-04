// S4 기준 보기 (읽기 전용)
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, PROGRAM_NAMES, type Program, type RuleSet } from "../api";
import { BY_LABEL, fmtDateTime, Spinner } from "../ui";

const PARAM_LABEL: Record<string, string> = {
  time: "결제 마감", limit: "한도(원)", minutes: "최소 시간(분)", allowed: "지역", meal_after: "식비 회의 후(분)",
  snack_before: "다과비 회의 전(분)", days: "제출 기한(일)", deadline_time: "마감 시각", card_word: "카드",
};

export default function RulesPage() {
  const { program = "club" } = useParams();
  const q = useQuery({ queryKey: ["rules", program], queryFn: () => api<RuleSet>(`/programs/${program}/rules`) });
  if (q.isLoading) return <div className="center-fill"><Spinner /> 불러오는 중…</div>;
  if (q.error) return <div className="center-fill"><div className="alert red">{(q.error as Error).message}</div></div>;
  const r = q.data!;
  const enabled = r.conditions.filter((c) => c.enabled);
  return (
    <main className="rules">
      <h1>{PROGRAM_NAMES[program as Program]} 검수 기준 <span className="muted">v{r.version}</span></h1>
      <p className="muted xsmall">
        {r.status === "confirmed" ? "확정" : "초안"} · {r.confirmed_by ?? "—"} · {fmtDateTime(r.confirmed_at)} · 조건 {enabled.length}개 적용, {r.conditions.length - enabled.length}개 제외 · 읽기 전용
      </p>
      {r.note && <div className="alert yellow small">{r.note}</div>}
      <table className="table rules-table">
        <thead><tr><th>ID</th><th>조건</th><th>판정 주체</th><th>미충족 시</th><th>파라미터</th><th>지침 원문</th></tr></thead>
        <tbody>
          {r.conditions.map((c) => (
            <tr key={c.id} className={c.enabled ? "" : "dim"}>
              <td className="mono">{c.id}</td>
              <td className="strong">{c.name}</td>
              <td>{c.enabled && c.by ? BY_LABEL[c.by] : "—"}</td>
              <td>{c.enabled ? <span className={`badge ${c.severity === "reject" ? "red" : "orange"}`}>{c.severity === "reject" ? "부적합" : "보완필요"}</span> : <span className="badge gray">제외</span>}</td>
              <td>{Object.entries(c.params ?? {}).filter(([k]) => PARAM_LABEL[k]).map(([k, v]) => (
                <span key={k} className="tag">{PARAM_LABEL[k]} {Array.isArray(v) ? v.join(", ") : String(v)}</span>
              ))}</td>
              <td className="muted xsmall">{c.enabled ? c.source : c.excluded_reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}
