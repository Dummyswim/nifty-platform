import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BarChart, CustomChart, ScatterChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { type EChartsType, init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { EventsOut, JobOut, LabelOut, ResearchOut, ResearchRow, SubmitOut } from "../api/schemas";
import { useUi } from "../store";
import { type Cell, type Cond, ciOption, eventsNear, fmt, labelOverlays, labelText } from "./view";

use([BarChart, CustomChart, ScatterChart, GridComponent, TooltipComponent, CanvasRenderer]);

const VARIANTS = ["anchor_cross_ema_order", "ema_gap_reexpansion", "ema_aligned_gap_reexpansion", "armed_resumption"];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const ist = (iso: string) => new Date(iso).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

function CiChart({ cells }: { cells: Cell[] }) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<EChartsType | null>(null);
  const option = useMemo(() => ciOption(cells), [cells]);
  useEffect(() => {
    const c = init(el.current!, "dark", { renderer: "canvas" });
    inst.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current!);
    return () => { ro.disconnect(); c.dispose(); };
  }, []);
  useEffect(() => inst.current?.setOption(option, true), [option]);
  return <div ref={el} className="echart" style={{ height: 40 + cells.length * 34 }} data-testid="ci-chart" />;
}

function NewRun({ symbol, onDone }: { symbol: string; onDone: (id: string) => void }) {
  const [variants, setVariants] = useState<string[]>(VARIANTS);
  const [t10, setT10] = useState(true);
  const [t20, setT20] = useState(true);
  const [cost, setCost] = useState("0");
  const [seed, setSeed] = useState("1");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg("queued…");
    try {
      const experiments = [t10 ? 10 : 0, t20 ? 20 : 0].filter(Boolean);
      const sub = await api<SubmitOut>("/research/runs", { body: { symbol, variants, experiments, cost_pts: Number(cost), seed: Number(seed) } });
      for (let i = 0; i < 400; i++) {
        const j = await api<JobOut>(`/jobs/${sub.job_id}`);
        setMsg(j.status === "running" ? "running…" : j.status);
        if (j.status === "done" && j.result_ref) return onDone(j.result_ref);
        if (j.status === "failed") throw new Error(j.error ?? "failed");
        await sleep(i < 4 ? 250 : 1000);
      }
      throw new Error("timed out");
    } catch (err) {
      setMsg(`failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="newrun" onSubmit={(e) => void submit(e)} aria-label="New research run">
      {VARIANTS.map((v) => (
        <label key={v} className="chk"><input type="checkbox" checked={variants.includes(v)} onChange={(e) => setVariants(e.target.checked ? [...variants, v] : variants.filter((x) => x !== v))} /> {v}</label>
      ))}
      <label className="chk"><input type="checkbox" checked={t10} onChange={(e) => setT10(e.target.checked)} /> target 10</label>
      <label className="chk"><input type="checkbox" checked={t20} onChange={(e) => setT20(e.target.checked)} /> target 20</label>
      <label>cost_pts <input type="number" min="0" step="any" value={cost} onChange={(e) => setCost(e.target.value)} /></label>
      <label>seed <input type="number" step="1" value={seed} onChange={(e) => setSeed(e.target.value)} /></label>
      <button type="submit" disabled={busy || !variants.length || !(t10 || t20)} data-testid="run-research">Run research</button>
      {msg && <span className={msg.startsWith("failed") ? "error" : "muted"} role="status">{msg}</span>}
    </form>
  );
}

function Conditions({ conds }: { conds: Cond[] }) {
  return (
    <ul className="conds">
      {conds.map((c) => <li key={c.name} className={c.passed ? "ok" : "bad"}>{c.passed ? "✔" : "✘"} {c.name} <span className="muted">({c.detail})</span></li>)}
    </ul>
  );
}

function Drill({ run, cell }: { run: ResearchOut; cell: Cell }) {
  const set = useUi((s) => s.set);
  const [sel, setSel] = useState<LabelOut | null>(null);
  const labels = useQuery({
    queryKey: ["labels", run.research_id, cell.variant, cell.experiment],
    queryFn: () => api<LabelOut[]>(`/research/runs/${run.research_id}/labels?variant=${cell.variant}&experiment=target_${cell.experiment}&limit=200`),
  });
  const events = useQuery({ queryKey: ["rs-events", cell.run_id], queryFn: () => api<EventsOut>(`/events?run_id=${cell.run_id}`) });
  const near = sel && events.data ? eventsNear(events.data.events, sel) : [];
  const open = () => {
    if (!sel) return;
    const from = Math.floor(Date.parse(sel.signal_bar_start) / 1000) - 600;
    set({ page: "chart", tf: "1m", focus: { from, to: Math.floor(Date.parse(sel.trade.exit_time) / 1000) + 600, nonce: Date.now(), tf: "1m", extra: labelOverlays(sel, near) } });
  };
  return (
    <section data-testid="rs-drill">
      <h4>Labels · {cell.variant} · target {cell.experiment} <span className="muted small">(experimental, paper only)</span></h4>
      <table className="trades">
        <thead><tr><th>Split</th><th>Label</th><th>Signal (IST)</th><th>Outcome</th><th>Net pts</th></tr></thead>
        <tbody>
          {(labels.data ?? []).map((l) => (
            <tr key={l.id} onClick={() => setSel(l)} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(l)} className={l.trade.net_pts > 0 ? "win" : "loss"} data-testid="label-row">
              <td>{l.split}</td><td>{l.label}</td><td>{ist(l.signal_bar_start)}</td><td>{l.trade.exit_reason}</td><td>{l.trade.net_pts.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {sel && (
        <aside className="drawer" role="dialog" aria-label="Label diagnostics" data-testid="rs-diag">
          <header><h3>{labelText(sel.side)}</h3><button className="ghost" onClick={() => setSel(null)} aria-label="Close">✕</button></header>
          <dl>
            <dt>Entry</dt><dd>{ist(sel.trade.entry_time)} @ {sel.trade.entry_px.toFixed(2)}</dd>
            <dt>Exit</dt><dd>{ist(sel.trade.exit_time)} @ {sel.trade.exit_px.toFixed(2)} · {sel.trade.exit_reason}</dd>
            <dt>Net / R</dt><dd>{sel.trade.net_pts.toFixed(2)} pts / {fmt(sel.trade.r_multiple)}</dd>
            <dt>MAE / MFE</dt><dd>{fmt(sel.trade.mae_pts)} / {fmt(sel.trade.mfe_pts)} pts</dd>
            <dt>Flags</dt><dd>{sel.trade.flags?.join(", ") || "none"}</dd>
            <dt>Events</dt><dd>{near.map((e) => e.event_type.replace("research.", "")).join(" → ") || "n/a"}</dd>
          </dl>
          <p className="muted small">Descriptive research only. Not a prediction and not an order.</p>
          <button onClick={open} data-testid="rs-open-chart">Open on chart</button>
        </aside>
      )}
    </section>
  );
}

function Detail({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["research", id], queryFn: () => api<ResearchOut>(`/research/runs/${id}`) });
  const [pick, setPick] = useState(0);
  const run = q.data;
  if (!run) return <p className="muted">Loading…</p>;
  const cells = (run.result?.cells ?? []) as Cell[];
  const v = run.result?.verdict as { verdict: string; reason: string } | undefined;
  const cell = cells[pick];
  return (
    <section data-testid="rs-detail">
      {run.status === "failed" && <p role="alert" className="error">Run failed: {run.error}</p>}
      {v && (
        <div className={`rs-banner ${v.verdict}`} data-testid="rs-verdict" data-verdict={v.verdict} role="status">
          <strong>{v.verdict.replace(/_/g, " ").toUpperCase()}</strong> — {v.reason}. <span className="muted">status: experimental · {run.splits.dev.length}/{run.splits.val.length}/{run.splits.eval.length} sessions (dev/val/eval) · seed {run.seed} · cost {run.cost_pts} pts</span>
        </div>
      )}
      {cell && <Conditions conds={cell.verdict.conditions} />}
      {cells.length > 0 && <CiChart cells={cells} />}
      <table className="trades" data-testid="rs-table">
        <thead><tr><th>Variant</th><th>Target</th><th>Trades</th><th>Target</th><th>Stop</th><th>Time</th><th>Ambig.</th><th>Interr.</th><th>Eval exp.</th><th>95% CI</th><th>Verdict</th></tr></thead>
        <tbody>
          {cells.map((c, i) => {
            const s = c.stats.splits.eval;
            return (
              <tr key={`${c.variant}${c.experiment}`} onClick={() => setPick(i)} className={i === pick ? "on" : ""} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setPick(i)}>
                <td>{c.variant}</td><td>{c.experiment}</td><td>{c.stats.n_trades}</td><td>{s.TARGET_FIRST}</td><td>{s.STOP_FIRST}</td><td>{s.TIME_EXIT}</td><td>{s.ambiguous}</td><td>{s.interrupted}</td>
                <td>{fmt(s.expectancy_pts)}</td><td>[{fmt(s.ci_lo)}, {fmt(s.ci_hi)}]</td><td>{c.verdict.verdict}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="muted small">Outcome columns count the untouched evaluation split; "Trades" counts all splits. {cells.length} variant×experiment cells were tested (multiple comparisons).</p>
      {cell && <Drill run={run} cell={cell} />}
    </section>
  );
}

export default function Research() {
  const { symbol } = useUi();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["research-runs"], queryFn: () => api<ResearchRow[]>("/research/runs") });
  const [sel, setSel] = useState<string | null>(null);
  const cur = sel ?? list.data?.[0]?.research_id ?? null;
  return (
    <div className="page backtests research">
      <h2>Research <span className="muted small">index-only · paper only · experimental</span></h2>
      <NewRun symbol={symbol} onDone={(id) => { void qc.invalidateQueries({ queryKey: ["research-runs"] }); setSel(id); }} />
      <div className="split">
        <ul className="btlist" aria-label="Research runs">
          {(list.data ?? []).map((r) => (
            <li key={r.research_id}><button className={r.research_id === cur ? "on" : ""} onClick={() => setSel(r.research_id)}>{r.research_id.slice(0, 11)} · {r.verdict ?? r.status}</button></li>
          ))}
          {list.data?.length === 0 && <li className="muted">No research runs yet.</li>}
        </ul>
        <div className="detail">{cur ? <Detail id={cur} /> : <p className="muted">Run research to see results.</p>}</div>
      </div>
    </div>
  );
}
