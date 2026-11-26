import { TFS, type Tf } from "./geometry";

/** Chart page layout: 1 pane, 2 side by side [A|B], or 3 = A big left with B over C on the right. */
export type LayoutN = 1 | 2 | 3;
export interface PaneState { symbol: string; tf: Tf; kind: "index" | "option"; label?: string }
/** col: left column width fraction; row: B's height fraction in the right column (layout 3) */
export interface Sizes { col: number; row: number }
export interface ChartLayout { layout: LayoutN; active: number; panes: PaneState[]; sizes: Sizes }

export const MIN_FRAC = 0.15;

export function clampFrac(f: number): number {
  if (!Number.isFinite(f)) return 0.5;
  return Math.min(1 - MIN_FRAC, Math.max(MIN_FRAC, f));
}

export function dragFrac(startFrac: number, deltaPx: number, totalPx: number): number {
  if (!(totalPx > 0)) return clampFrac(startFrac);
  return clampFrac(startFrac + deltaPx / totalPx);
}

export function defaultLayout(symbol: string, tf: Tf): ChartLayout {
  return { layout: 1, active: 0, panes: [{ symbol, tf, kind: "index" }], sizes: { col: 0.5, row: 0.5 } };
}

export function setLayoutN(l: ChartLayout, n: LayoutN): ChartLayout {
  const src = l.panes[l.active] ?? l.panes[0]!;
  const panes = l.panes.slice(0, n);
  while (panes.length < n) panes.push({ ...src });
  return { ...l, layout: n, panes, active: Math.min(l.active, n - 1) };
}

export function updatePane(l: ChartLayout, i: number, p: Partial<PaneState>): ChartLayout {
  return { ...l, panes: l.panes.map((x, j) => (j === i ? { ...x, ...p } : x)) };
}

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const asTf = (v: unknown, fb: Tf): Tf => (TFS as readonly unknown[]).includes(v) ? (v as Tf) : fb;

function asPane(v: unknown, fb: { symbol: string; tf: Tf }): PaneState | null {
  if (!isObj(v) || typeof v.symbol !== "string" || !v.symbol) return null;
  const p: PaneState = { symbol: v.symbol, tf: asTf(v.tf, fb.tf), kind: v.kind === "option" ? "option" : "index" };
  if (typeof v.label === "string") p.label = v.label;
  return p;
}

/** Restore from the `chart_layout` pref; falls back to the old `chart` pref ({symbol, tf}) and then `fb`. */
export function fromPrefs(chartLayout: unknown, chart: unknown, fb: { symbol: string; tf: Tf }): ChartLayout {
  const old = isObj(chart) && typeof chart.symbol === "string" && chart.symbol
    ? { symbol: chart.symbol, tf: asTf(chart.tf, fb.tf) }
    : fb;
  const base = defaultLayout(old.symbol, old.tf);
  if (!isObj(chartLayout)) return base;
  const n: LayoutN = chartLayout.layout === 2 || chartLayout.layout === 3 ? chartLayout.layout : 1;
  const panes = (Array.isArray(chartLayout.panes) ? chartLayout.panes : [])
    .map((p) => asPane(p, fb))
    .filter((p): p is PaneState => p !== null)
    .slice(0, n);
  if (!panes.length) panes.push(base.panes[0]!);
  while (panes.length < n) panes.push({ ...panes[0]! });
  const a = chartLayout.active;
  const active = typeof a === "number" && Number.isInteger(a) && a >= 0 && a < n ? a : 0;
  const s = isObj(chartLayout.sizes) ? chartLayout.sizes : {};
  const sizes = { col: typeof s.col === "number" ? clampFrac(s.col) : 0.5, row: typeof s.row === "number" ? clampFrac(s.row) : 0.5 };
  return { layout: n, active, panes, sizes };
}

export function toPrefs(l: ChartLayout): { chart_layout: ChartLayout; chart: { symbol: string; tf: Tf } } {
  const a = l.panes[0]!;
  return { chart_layout: l, chart: { symbol: a.symbol, tf: a.tf } };
}
