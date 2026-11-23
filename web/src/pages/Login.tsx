import { useState } from "react";
import { api } from "../api/client";

export function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/login", { body: { password } });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="login">
      <form className="card" onSubmit={(e) => void submit(e)}>
        <div className="logo" aria-hidden>
          ◢
        </div>
        <h1>NIFTY Platform</h1>
        <p className="muted">Options research workspace</p>
        <label>
          Password
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        <button type="submit" disabled={busy || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
      </form>
    </main>
  );
}
