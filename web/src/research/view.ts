import type { EventsOut, LabelOut } from "../api/schemas";
import type { El } from "../overlay/pick";

export type Ev = EventsOut["events"][number];
export interface Cond { name: string; passed: boolean; detail: string }
export interface Split { sessions: number; n: number; TARGET_FIRST: number; STOP_FIRST: number; TIME_EXIT: number; ambiguous: number; interrupted: number; expectancy_pts: number | null; ci_lo: number | null; ci_hi: number | null }
export interface Cell {
  variant: string; experiment: number; run_id: string;
  stats: { n_trades: number; n_purged: number; loso_min_eval: number | null; loso_n: number; splits: Record<"dev" | "val" | "eval", Split> };
  verdict: { verdict: string; reason: string; conditions: Cond[] };
}

const sec = (iso: string) => Math.floor(Date.parse(iso) / 1000);
export const fmt = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "n/a" : x.toFixed(d));

/** Label text for the side; never claims independent confirmations. */
export const labelText = (side: string) => (side === "short" ? "BEARISH INDEX / PUT CANDIDATE" : "BULLISH INDEX / CALL CANDIDATE");

/** Events of one label: from 30 min before its signal bar to its exit. */
export function eventsNear(events: Ev[], l: LabelOut): Ev[] {
  const lo = sec(l.signal_bar_start) - 30 * 60;
  const hi = sec(l.trade.exit_time) + 60;
  return events.filter((e) => { const t = sec(e.bar_start_utc); return t >= lo && t <= hi; });
}

const ROLE: Record<string, string> = { "research.watch": "info", "research.armed": "warn", "research.entry": "bull", "research.exit": "info", "research.invalidated": "bear" };

/** Markers for watch/armed/entry/exit/invalidation plus stop/target/entry lines; drawn by the chart page. */
export function labelOverlays(l: LabelOut, events: Ev[]): El[] {
  const t = l.trade;
  const from = sec(l.signal_bar_start);
  const to = sec(t.exit_time);
  const base = { ver: 0, deleted: false, avail: 0, p1: null, text: null, meta: {} };
  const out: El[] = [];
  const ent = events.find((e) => e.event_type === "research.entry" && sec(String(e.payload?.signal_bar_start)) === from);
  const px = (k: string) => (typeof ent?.payload?.[k] === "number" ? (ent.payload[k] as number) : null);
  const line = (id: string, price: number | null, role: string, text: string) => {
    if (price !== null) out.push({ ...base, id: `rs:${id}`, kind: "line", t0: from, t1: to, p0: price, p1: price, text, style: { role, dashed: id !== "entry" } });
  };
  line("entry", t.entry_px, t.side === "long" ? "bull" : "bear", "entry");
  line("stop", px("stop_px"), "bear", "stop");
  line("target", px("target_px"), "bull", "target");
  events.forEach((e, i) => {
    const kind = e.event_type.replace("research.", "");
    const label = kind === "exit" ? String(e.payload?.outcome ?? "exit") : kind;
    out.push({ ...base, id: `rs:ev:${i}`, kind: "marker", t0: sec(e.bar_start_utc), t1: null, p0: t.entry_px, text: label, style: { role: ROLE[e.event_type] ?? "info" } });
  });
  return out;
}

/** ECharts option: evaluation-split expectancy with its 95 % session-clustered CI per cell. */
export function ciOption(cells: Cell[]): Record<string, unknown> {
  const names = cells.map((c) => `${c.variant.replace(/_/g, " ")} · ${c.experiment}`);
  const ev = cells.map((c) => c.stats.splits.eval);
  return {
    backgroundColor: "transparent", tooltip: { trigger: "axis" },
    grid: { left: 210, right: 24, top: 16, bottom: 28 },
    xAxis: { type: "value", name: "net pts / trade (eval)" }, yAxis: { type: "category", data: names, inverse: true },
    series: [
      { type: "custom", name: "95% CI", data: ev.map((s, i) => [i, s.ci_lo, s.ci_hi, s.expectancy_pts]),
        renderItem: (_p: unknown, api: { value: (n: number) => number; coord: (v: number[]) => number[]; size: (v: number[]) => number[] }) => {
          const lo = api.value(1), hi = api.value(2), i = api.value(0);
          if (Number.isNaN(lo) || Number.isNaN(hi)) return { type: "group", children: [] };
          const a = api.coord([lo, i]), b = api.coord([hi, i]), h = api.size([0, 1])[1] * 0.3;
          return { type: "rect", shape: { x: a[0], y: a[1] - h / 2, width: Math.max(b[0] - a[0], 1), height: h }, style: { fill: "#4c8dff55", stroke: "#4c8dff" } };
        } },
      { type: "scatter", name: "expectancy", data: ev.map((s, i) => [s.expectancy_pts, i]), symbolSize: 8 },
    ],
  };
}
