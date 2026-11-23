import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, TooltipComponent } from "echarts/components";
import { type EChartsType, init, use } from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { api } from "../api/client";
import type { BacktestOut, BacktestRow, TradeOut } from "../api/schemas";
import { useUi } from "../store";
import { MetricCards } from "./Metrics";
import { curves, histogram } from "./series";

use([LineChart, BarChart, GridComponent, TooltipComponent, CanvasRenderer]);

function Chart({ option, id }: { option: Record<string, unknown>; id: string }) {
  const el = useRef<HTMLDivElement>(null);
  const inst = useRef<EChartsType | null>(null);
  useEffect(() => {
    const c = init(el.current!, "dark", { renderer: "canvas" });
    inst.current = c;
    const ro = new ResizeObserver(() => c.resize());
    ro.observe(el.current!);
    return () => { ro.disconnect(); c.dispose(); };
  }, []);
  useEffect(() => inst.current?.setOption(option, true), [option]);
  return <div ref={el} className="echart" data-testid={id} />;
}

const base = { backgroundColor: "transparent", grid: { left: 56, right: 16, top: 24, bottom: 28 }, tooltip: { trigger: "axis" } };

export default function Analytics() {
  const { backtestId } = useUi();
  const list = useQuery({ queryKey: ["backtests"], queryFn: () => api<BacktestRow[]>("/backtests") });
  const id = backtestId ?? list.data?.[0]?.backtest_id ?? null;
  const bt = useQuery({ queryKey: ["backtest", id], queryFn: () => api<BacktestOut>(`/backtests/${id}`), enabled: !!id });
  const trades = useQuery({ queryKey: ["trades", id], queryFn: () => api<TradeOut[]>(`/backtests/${id}/trades`), enabled: !!id });
  const c = useMemo(() => curves(trades.data ?? []), [trades.data]);
  const x = c.t.map((t) => new Date(t * 1000).toLocaleString("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }));
  const hist = useMemo(() => histogram(c.sessions.map((s) => s.pnl)), [c.sessions]);
  const equity = useMemo(() => ({ ...base, xAxis: { type: "category", data: x }, yAxis: { type: "value", name: "pts" }, series: [{ type: "line", data: c.equity, step: "end", showSymbol: false, areaStyle: { opacity: 0.12 } }] }), [c, x]);
  const dd = useMemo(() => ({ ...base, xAxis: { type: "category", data: x }, yAxis: { type: "value", name: "pts" }, series: [{ type: "line", data: c.drawdown, showSymbol: false, color: "#ef5350", areaStyle: { opacity: 0.2 } }] }), [c, x]);
  const hs = useMemo(() => ({ ...base, xAxis: { type: "category", data: hist.map((b) => `${b.lo.toFixed(0)}…${b.hi.toFixed(0)}`), name: "session P&L (pts)" }, yAxis: { type: "value", name: "sessions", minInterval: 1 }, series: [{ type: "bar", data: hist.map((b) => b.n), color: "#4c8dff" }] }), [hist]);
  if (!id) return <div className="page"><h2>Analytics</h2><p className="muted">Run a backtest first.</p></div>;
  return (
    <div className="page analytics">
      <h2>Analytics</h2>
      {bt.data && <p className="muted small">{bt.data.engine_id} · {bt.data.timeframe} · {bt.data.backtest_id}</p>}
      {bt.data && <MetricCards m={bt.data.summary} />}
      <h3>Equity (cumulative net points)</h3>
      <Chart id="equity" option={equity} />
      <h3>Drawdown</h3>
      <Chart id="drawdown" option={dd} />
      <h3>Per-session P&L</h3>
      <Chart id="session-hist" option={hs} />
    </div>
  );
}
