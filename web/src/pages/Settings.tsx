import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { JobOut, KiteStatusOut, LoginUrlOut, SubmitOut } from "../api/schemas";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const ist = (iso?: string | null) => (iso ? new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Kolkata" }) : "never");

/** Submit a job and follow it to the end; `onTick` receives the status text. */
async function followJob(sub: SubmitOut, onTick: (s: string) => void): Promise<string> {
  for (let i = 0; i < 600; i++) {
    const j = await api<JobOut>(`/jobs/${sub.job_id}`);
    onTick(j.status === "queued" ? "queued…" : j.status === "running" ? "running…" : j.status);
    if (j.status === "done") return j.result_ref ?? "done";
    if (j.status === "failed") throw new Error(j.error ?? "failed");
    await sleep(i < 4 ? 300 : 1000);
  }
  throw new Error("timed out");
}

function KiteSection() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["kite-status"], queryFn: () => api<KiteStatusOut>("/kite/status") });
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const result = new URLSearchParams(window.location.search).get("kite");
  const s = status.data;

  const connect = async () => {
    const { url } = await api<LoginUrlOut>("/kite/login-url");
    window.location.href = url; // the user logs in on Kite; the callback returns here
  };
  const run = async (path: string, body: unknown) => {
    setBusy(true);
    setMsg("queued…");
    try {
      const sub = await api<SubmitOut>(path, { body });
      setMsg(await followJob(sub, setMsg));
      void qc.invalidateQueries({ queryKey: ["kite-status"] });
    } catch (e) {
      setMsg(`failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section data-testid="kite">
      <h3>Kite</h3>
      {result === "connected" && <p className="chip ready">Connected to Kite.</p>}
      {result === "error" && <p className="chip failed" role="alert">Kite login failed. Try again.</p>}
      <p>
        <span className={`chip ${s?.connected ? "ready" : "failed"}`} data-testid="kite-badge">
          {!s ? "…" : !s.configured ? "not configured" : s.connected ? "connected" : "not connected"}
        </span>{" "}
        {s?.user_id && <span className="muted">user {s.user_id} · token expires {ist(s.expires_at)} IST</span>}
      </p>
      {s && !s.configured && <p className="muted small">Put KITE_API_KEY and KITE_API_SECRET in .env, then restart the API.</p>}
      {s?.last_error && <p className="error small">{s.last_error}</p>}
      <p className="muted small">Kite requires a login once per trading day (the token expires at 06:00 IST). Open this app at 127.0.0.1, not localhost.</p>
      <div className="row gap">
        <button onClick={() => void connect()} disabled={!s?.configured}>{s?.connected ? "Reconnect Kite" : "Connect Kite"}</button>
        <button onClick={() => void run("/kite/instruments/refresh", {})} disabled={busy || !s?.connected}>Refresh instruments</button>
        <span className="muted small">instruments updated: {ist(s?.instruments_updated_at)} IST</span>
      </div>
      <div className="row gap">
        <label>Backfill from <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label>to <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <button onClick={() => void run("/kite/backfill", { symbol: "NIFTY 50", from_date: from, to_date: to })} disabled={busy || !s?.connected || !from || !to}>
          Backfill NIFTY 50 (1m)
        </button>
      </div>
      {msg && <p role="status" className={msg.startsWith("failed") ? "error small" : "muted small"} data-testid="kite-msg">{msg}</p>}
    </section>
  );
}

export function Settings() {
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  return (
    <div className="panel">
      <h2>Settings</h2>
      <KiteSection />
      <section>
        <h3>Preferences</h3>
        {prefs.isLoading ? <p className="muted">Loading…</p> : <pre data-testid="prefs">{JSON.stringify(prefs.data ?? {}, null, 2)}</pre>}
      </section>
    </div>
  );
}
