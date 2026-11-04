import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, token, type User } from "../api";

const ACCOUNTS = [
  { id: "club-manager", label: "동아리 담당자" },
  { id: "wemeet-manager", label: "위밋 담당자" },
  { id: "admin", label: "관리자" },
];

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const nav = useNavigate();
  const qc = useQueryClient();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string; user: User }>("/auth/login", { method: "POST", json: { username, password } });
      token.set(r.access_token);
      qc.setQueryData(["me"], r.user);
      nav(`/${r.user.programs[0]}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "로그인할 수 없습니다.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand"><span className="logo" />회의비 증빙 검수</div>
        <p className="muted small">인공지능혁신융합대학사업단 담당자 전용</p>
        <label>아이디<input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" /></label>
        <label>비밀번호<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <div className="alert red">{error}</div>}
        <button className="primary block" disabled={busy || !username || !password}>{busy ? "로그인 중…" : "로그인"}</button>
        <div className="divider" />
        <p className="muted xsmall">계정을 누르면 아이디가 채워집니다</p>
        <div className="chips">
          {ACCOUNTS.map((a) => (
            <button type="button" key={a.id} className="chip" onClick={() => setUsername(a.id)}>{a.label}</button>
          ))}
        </div>
      </form>
    </div>
  );
}
