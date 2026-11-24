import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { BacktestOut, BacktestRow, EngineOut, JobOut, SubmitOut, TradeOut } from "../api/schemas";
import { FieldInput } from "../indicators/IndicatorPanel";
import { type Values, coerce, defaultsOf, paramsForRun } from "../indicators/schemaForm";
import { fieldsOf } from "../indicators/useIndicators";
import { useUi } from "../store";
import { AuditDrawer } from "./AuditDrawer";
import { MetricCards } from "./Metrics";
import { type Filters, NO_FILTER, type SortKey, filterTrades, reasonsOf, sortTrades } from "./tradeTable";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function NewRun({ engines, symbol, onDone }: { engines: EngineOut[]; symbol: string; onDone: (id: string) => void }) {
  // Balu is an indicator (no trades): default to the strategy engine
  const [engineId, setEngineId] = useState((engines.find((e) => e.id === "pine.nvs_scalper") ?? engines[0])?.id ?? "");
  const engine = engines.find((e) => e.id === engineId);
  const fields = useMemo(() => (engine ? fieldsOf(engine).filter((f) => !f.ui) : []), [engine]);
  const [vals, setVals] = useState<Values["params"]>({});
  const [tf, setTf] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [mode, setMode] = useState<"tv" | "conservative">("tv");
  const [qty, setQty] = useState("1");
  const [cost, setCost] = useState("0");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [showParams, setShowParams] = useState(false);
  const [opt, setOpt] = useState(false);
  const [strikeType, setStrikeType] = useState("ATM");
  const [expiryKind, setExpiryKind] = useState("current weekly");
  const [lots, setLots] = useState("1");
  const [costInr, setCostInr] = useState("0");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!engine) return;
    setBusy(true);
    setMsg("queued…");
    try {
      const params = paramsForRun(fields, { ...defaultsOf(fields).params, ...vals });
      const body = {
        engine_id: engine.id, symbol, timeframe: tf || engine.default_timeframe, params, mode,
        qty: Number(qty), cost_pts: Number(cost), ...(from ? { from_date: from } : {}), ...(to ? { to_date: to } : {}),
        ...(opt ? { option_policy: { strike_type: strikeType, expiry_kind: expiryKind, lots: Number(lots), cost_inr: Number(costInr) } } : {}),
      };
      const sub = await api<SubmitOut>("/backtests", { body });
      for (let i = 0; i < 240; i++) {
        const j = await api<JobOut>(`/jobs/${sub.job_id}`);
        setMsg(j.status === "running" ? "running…" : j.status);
        if (j.status === "done" && j.backtest_id) return onDone(j.backtest_id);
        if (j.status === "failed") throw new Error(j.error ?? "failed");
        await sleep(i < 4 ? 250 : 750);
      }
      throw new Error("timed out");
    } catch (err) {
      setMsg(`failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="newrun" onSubmit={(e) => void submit(e)} aria-label="New backtest">
      <label>Engine
        <select value={engineId} onChange={(e) => { setEngineId(e.target.value); setVals({}); }}>
          {engines.map((e) => <option key={e.id}>{e.id}</option>)}
        </select>
      </label>
      <label>Timeframe
        <select value={tf || engine?.default_timeframe || "5m"} onChange={(e) => setTf(e.target.value)}>
          {["1m", "3m", "5m", "10m", "15m", "30m", "1h"].map((t) => <option key={t}>{t}</option>)}
        </select>
      </label>
      <label>From <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
      <label>To <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
      <label>Mode
        <select value={mode} onChange={(e) => setMode(e.target.value as "tv" | "conservative")}>
          <option value="tv">tv (Pine)</option><option value="conservative">conservative</option>
        </select>
      </label>
      <label>Qty <input type="number" min="0" step="any" value={qty} onChange={(e) => setQty(e.target.value)} /></label>
      <label>cost_pts <input type="number" min="0" step="any" value={cost} onChange={(e) => setCost(e.target.value)} /></label>
      <label className="chk"><input type="checkbox" checked={opt} onChange={(e) => setOpt(e.target.checked)} aria-label="Map to options" /> Map to options (CE/PE paper)</label>
      {opt && (
        <>
          <label>Strike type <select value={strikeType} onChange={(e) => setStrikeType(e.target.value)}>{["Deep ITM", "ITM", "ATM", "OTM", "Deep OTM"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label>Expiry <select value={expiryKind} onChange={(e) => setExpiryKind(e.target.value)}>{["current weekly", "next weekly", "monthly"].map((x) => <option key={x}>{x}</option>)}</select></label>
          <label>Lots <input type="number" min="1" step="1" value={lots} onChange={(e) => setLots(e.target.value)} /></label>
          <label>cost_inr <input type="number" min="0" step="any" value={costInr} onChange={(e) => setCostInr(e.target.value)} /></label>
        </>
      )}
      <button type="button" className="ghost" onClick={() => setShowParams(!showParams)}>Params</button>
      <button type="submit" disabled={busy || !engine} data-testid="run-backtest">Run backtest</button>
      {msg && <span className={msg.startsWith("failed") ? "error" : "muted"} role="status">{msg}</span>}
      {showParams && (
        <div className="form wide">
          {fields.map((f) => (
            <label key={f.key} className="f">
              <span>{f.title}</span>
              <FieldInput f={f} value={vals[f.key] ?? f.def} onChange={(v) => setVals({ ...vals, [f.key]: v })} />
            </label>
          ))}
        </div>
      )}
    </form>
  );
}

function Detail({ id }: { id: string }) {
  const bt = useQuery({ queryKey: ["backtest", id], queryFn: () => api<BacktestOut>(`/backtests/${id}`) });
  const trades = useQuery({ queryKey: ["trades", id], queryFn: () => api<TradeOut[]>(`/backtests/${id}/trades`) });
  const [f, setF] = useState<Filters>(NO_FILTER);
  const [key, setKey] = useState<SortKey>("entry_time");
  const [dir, setDir] = useState<1 | -1>(1);
  const [audit, setAudit] = useState<string | null>(null);
  const rows = useMemo(() => sortTrades(filterTrades(trades.data ?? [], f), key, dir), [trades.data, f, key, dir]);
  const hasOpt = (trades.data ?? []).some((t) => t.contract_id);
  if (!bt.data) return <p className="muted">Loading…</p>;
  const th = (k: SortKey, label: string) => (
    <th onClick={() => (k === key ? setDir(dir === 1 ? -1 : 1) : (setKey(k), setDir(1)))} aria-sort={k === key ? (dir === 1 ? "ascending" : "descending") : "none"}>
      {label}{k === key ? (dir === 1 ? " ▲" : " ▼") : ""}
    </th>
  );
  const ist = (iso: string) => new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  return (
    <section data-testid="bt-detail">
      <h3>{bt.data.engine_id} · {bt.data.timeframe} · {bt.data.mode}</h3>
      <p className="muted small">{bt.data.backtest_id} · {bt.data.snapshot_id}</p>
      <MetricCards m={bt.data.summary} />
      <div className="row gap">
        <select value={f.side} onChange={(e) => setF({ ...f, side: e.target.value as Filters["side"] })} aria-label="Side filter">
          <option value="all">all sides</option><option value="long">long</option><option value="short">short</option>
        </select>
        <select value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} aria-label="Reason filter">
          <option value="all">all reasons</option>{reasonsOf(trades.data ?? []).map((r) => <option key={r}>{r}</option>)}
        </select>
        <select value={f.result} onChange={(e) => setF({ ...f, result: e.target.value as Filters["result"] })} aria-label="Result filter">
          <option value="all">all results</option><option value="win">wins</option><option value="loss">losses</option>
        </select>
        <span className="spacer" />
        {(["csv", "xlsx", "json"] as const).map((x) => (
          <a key={x} className="btn" href={`/api/v1/backtests/${id}/export?fmt=${x}`} download>{x.toUpperCase()}</a>
        ))}
      </div>
      <table className="trades" data-testid="trades">
        <thead><tr>{th("side", "Side")}{th("entry_time", "Entry (IST)")}<th>Entry px</th>{th("exit_time", "Exit (IST)")}<th>Exit px</th>{th("exit_reason", "Reason")}{th("net_pts", "Net pts")}{th("r_multiple", "R")}{th("bars_held", "Bars")}{hasOpt && <><th>Contract</th><th>Entry prem</th><th>Exit prem</th><th>P&L ₹</th></>}</tr></thead>
        <tbody>
          {rows.map((t) => (
            <tr key={t.trade_id} onClick={() => setAudit(t.trade_id)} className={t.net_pts > 0 ? "win" : "loss"} data-testid="trade-row" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setAudit(t.trade_id)}>
              <td>{t.side}</td><td>{ist(t.entry_time)}</td><td>{t.entry_px.toFixed(2)}</td><td>{ist(t.exit_time)}</td><td>{t.exit_px.toFixed(2)}</td>
              <td>{t.exit_reason}</td><td>{t.net_pts.toFixed(2)}</td><td>{t.r_multiple?.toFixed(2) ?? "n/a"}</td><td>{t.bars_held}</td>
              {hasOpt && (
                <>
                  <td>{t.contract_id ?? "no quote"}</td><td>{t.entry_prem?.toFixed(2) ?? "—"}</td><td>{t.exit_prem?.toFixed(2) ?? "—"}</td>
                  <td>{t.pnl_inr != null ? `${t.pnl_inr.toFixed(0)}${t.synthetic ? " (synth. exit)" : ""}` : "—"}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {audit && <AuditDrawer bt={bt.data} tradeId={audit} onClose={() => setAudit(null)} />}
    </section>
  );
}

export function Backtests() {
  const { symbol, backtestId, set } = useUi();
  const qc = useQueryClient();
  const engines = useQuery({ queryKey: ["engines"], queryFn: () => api<EngineOut[]>("/engines") });
  const list = useQuery({ queryKey: ["backtests"], queryFn: () => api<BacktestRow[]>("/backtests") });
  const sel = backtestId ?? list.data?.[0]?.backtest_id ?? null;
  return (
    <div className="page backtests">
      <h2>Backtests</h2>
      {engines.data && <NewRun engines={engines.data} symbol={symbol} onDone={(id) => { void qc.invalidateQueries({ queryKey: ["backtests"] }); set({ backtestId: id }); }} />}
      <div className="split">
        <ul className="btlist" aria-label="Backtests">
          {(list.data ?? []).map((b) => (
            <li key={b.backtest_id}>
              <button className={b.backtest_id === sel ? "on" : ""} onClick={() => set({ backtestId: b.backtest_id })}>
                {b.engine_id} {b.timeframe} · {b.n_trades ?? 0} trades · {Number(b.total_pnl_pts ?? 0).toFixed(1)} pts
              </button>
            </li>
          ))}
          {list.data?.length === 0 && <li className="muted">No backtests yet.</li>}
        </ul>
        <div className="detail">{sel ? <Detail id={sel} /> : <p className="muted">Run a backtest to see results.</p>}</div>
      </div>
    </div>
  );
}
