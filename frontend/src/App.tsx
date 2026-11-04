import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, PROGRAM_NAMES, qs, token, type Page, type SubmissionListItem, type User } from "./api";
import DetailPage from "./pages/DetailPage";
import ListPage from "./pages/ListPage";
import LoginPage from "./pages/LoginPage";
import RulesPage from "./pages/RulesPage";
import { Spinner } from "./ui";

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<User>("/auth/me"), enabled: !!token.get(), staleTime: Infinity });
}

function TopBar({ user }: { user: User }) {
  const nav = useNavigate();
  const qc = useQueryClient();
  const loc = useLocation();
  const rules = loc.pathname.endsWith("/rules");
  const unassigned = useQuery({
    queryKey: ["unassigned-count"],
    queryFn: () => api<Page<SubmissionListItem>>(`/programs/unassigned/submissions${qs({ size: 1 })}`),
    refetchInterval: 60_000,
  });
  const current = loc.pathname.split("/")[1];
  return (
    <header className="topbar">
      <div className="brand" onClick={() => nav(`/${user.programs[0]}`)}><span className="logo" />회의비 증빙 검수</div>
      <nav className="tabs">
        {user.programs.map((p) => (
          <NavLink key={p} to={rules ? `/${p}/rules` : `/${p}`} className={() => (current === p ? "tab active" : "tab")}>
            {PROGRAM_NAMES[p]}
          </NavLink>
        ))}
        {!!unassigned.data?.total && (
          <NavLink to="/unassigned" className={() => (current === "unassigned" ? "tab active warn" : "tab warn")}>
            프로그램 미확정 <span className="count">{unassigned.data.total}</span>
          </NavLink>
        )}
      </nav>
      <div className="topbar-right">
        {current && current !== "unassigned" && current !== "submissions" && (
          <button className={`ghost small ${rules ? "on" : ""}`} onClick={() => nav(rules ? `/${current}` : `/${current}/rules`)}>
            기준 보기
          </button>
        )}
        <span className="muted small">{user.name}</span>
        <button className="ghost small" onClick={() => { token.clear(); qc.clear(); nav("/login"); }}>⎋ 로그아웃</button>
      </div>
    </header>
  );
}

export default function App() {
  const me = useMe();
  const loc = useLocation();
  if (!token.get() && loc.pathname !== "/login") return <Navigate to="/login" replace />;
  if (loc.pathname === "/login") return <Routes><Route path="/login" element={<LoginPage />} /></Routes>;
  if (me.isLoading || !me.data) return <div className="center-fill"><Spinner /> 불러오는 중…</div>;
  const user = me.data;
  return (
    <div className="app">
      <TopBar user={user} />
      <Routes>
        <Route path="/" element={<Navigate to={`/${user.programs[0]}`} replace />} />
        <Route path="/submissions/:id" element={<DetailPage />} />
        <Route path="/unassigned" element={<ListPage program="unassigned" />} />
        <Route path="/:program/rules" element={<RulesPage />} />
        <Route path="/:program" element={<ListPage />} />
      </Routes>
    </div>
  );
}
