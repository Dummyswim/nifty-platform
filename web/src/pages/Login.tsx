import { useState } from "react";
import { api } from "../api/client";

export function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api("/auth/login", { body: { password } });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "login failed");
    }
  };
  return (
    <form onSubmit={(e) => void submit(e)}>
      <h1>NIFTY Platform</h1>
      <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" />
      <button type="submit">Sign in</button>
      {error && <p role="alert">{error}</p>}
    </form>
  );
}
