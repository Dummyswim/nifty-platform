import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
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

const OPT_DEFAULTS = { r: "", window: "5", stale: "60", cost: "0", offsets: { "Deep ITM": "5", ITM: "2", ATM: "0", OTM: "2", "Deep OTM": "5" } as Record<string, string> };

function OptionsSection() {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  const [f, setF] = useState(OPT_DEFAULTS);
  const [msg, setMsg] = useState("");
  const loaded = prefs.data;
  useEffect(() => {
    if (!loaded) return;
    const r = loaded["options.r"];
    const off = (loaded["options.strike_offsets"] ?? {}) as Record<string, number>;
    setF({
      r: typeof r === "number" ? String(r * 100) : "",
      window: String(loaded["options.window_steps"] ?? OPT_DEFAULTS.window),
      stale: String(loaded["options.max_stale_s"] ?? OPT_DEFAULTS.stale),
      cost: String(loaded["options.cost_inr"] ?? OPT_DEFAULTS.cost),
      offsets: { ...OPT_DEFAULTS.offsets, ...Object.fromEntries(Object.entries(off).map(([k, v]) => [k, String(v)])) },
    });
  }, [loaded]);
  const put = (key: string, value: unknown) => api(`/prefs/${key}`, { method: "PUT", body: { value } });
  const save = async () => {
    try {
      await Promise.all([
        put("options.r", f.r.trim() === "" ? null : Number(f.r) / 100), // no invented default: empty = Greeks n/a
        put("options.window_steps", Math.max(1, Math.round(Number(f.window)))),
        put("options.max_stale_s", Math.max(1, Number(f.stale))),
        put("options.cost_inr", Math.max(0, Number(f.cost))),
        put("options.strike_offsets", Object.fromEntries(Object.entries(f.offsets).map(([k, v]) => [k, Math.max(0, Math.round(Number(v)))]))),
      ]);
      void qc.invalidateQueries({ queryKey: ["prefs"] });
      setMsg("saved");
    } catch (e) {
      setMsg(`failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };
  return (
    <section data-testid="options-settings">
      <h3>Options</h3>
      <div className="form wide">
        <label className="f"><span>Risk-free rate r (% p.a.; empty = Greeks n/a)</span><input aria-label="Risk-free rate" value={f.r} onChange={(e) => setF({ ...f, r: e.target.value })} /></label>
        <label className="f"><span>Recording window (strikes each side of ATM)</span><input aria-label="Window steps" value={f.window} onChange={(e) => setF({ ...f, window: e.target.value })} /></label>
        <label className="f"><span>Max quote staleness for paper trades (s)</span><input aria-label="Max staleness" value={f.stale} onChange={(e) => setF({ ...f, stale: e.target.value })} /></label>
        <label className="f"><span>Paper trade cost (₹ per round trip)</span><input aria-label="Cost INR" value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value })} /></label>
        {Object.entries(f.offsets).map(([k, v]) => (
          <label className="f" key={k}><span>{k} (strike steps from ATM)</span><input aria-label={`Offset ${k}`} value={v} onChange={(e) => setF({ ...f, offsets: { ...f.offsets, [k]: e.target.value } })} /></label>
        ))}
      </div>
      <div className="row gap"><button onClick={() => void save()}>Save options settings</button>{msg && <span className={msg.startsWith("failed") ? "error small" : "muted small"} role="status">{msg}</span>}</div>
    </section>
  );
}

export function Settings() {
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  return (
    <div className="panel">
      <h2>Settings</h2>
      <KiteSection />
      <OptionsSection />
      <section>
        <h3>Preferences</h3>
        {prefs.isLoading ? <p className="muted">Loading…</p> : <pre data-testid="prefs">{JSON.stringify(prefs.data ?? {}, null, 2)}</pre>}
      </section>
    </div>
  );
}
