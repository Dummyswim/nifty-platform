import type { components } from "../api/types";
import { roleColor } from "./pick";

type Plots = components["schemas"]["PlotsOut"];
type Engine = components["schemas"]["EngineOut"];

export interface PlotLayer {
  key: string;
  name: string;
  kind: "line" | "step" | "hist" | "area";
  color: string;
  pane: "overlay" | "own";
  t: number[]; // engine bar start
  v: (number | null)[];
  barSec: number; // engine timeframe seconds: a point is known once its bar closed
}

const THIN = new Set(["buy_near", "buy_far", "sell_near", "sell_far"]);

/** plots + engine PlotSpecs -> drawable layers. `ui` colour overrides are `color_<role>` keys. */
export function plotLayers(engine: Engine, plots: Plots, barSec: number, ui: Record<string, unknown>): PlotLayer[] {
  const overrides: Record<string, string> = {};
  for (const [k, v] of Object.entries(ui)) if (k.startsWith("color_") && typeof v === "string") overrides[k.slice(6)] = v;
  return (engine.plots ?? [])
    .filter((s) => plots.series[s.name] && s.role !== "hidden") // "hidden" = data-window only
    .map((s) => ({
      key: `${engine.id}:${s.name}`,
      name: s.name,
      kind: s.kind,
      color: roleColor(s.role, overrides) + (THIN.has(s.name) ? "88" : ""),
      pane: s.pane,
      t: plots.t,
      v: plots.series[s.name]!,
      barSec,
    }));
}

/** Points known at the cursor (bar closed) as lightweight-charts data; null values are gaps. */
export function revealPlot(l: PlotLayer, cursor: number | null): { time: number; value?: number }[] {
  const out: { time: number; value?: number }[] = [];
  for (let i = 0; i < l.t.length; i++) {
    if (cursor !== null && l.t[i]! + l.barSec > cursor) break;
    const v = l.v[i];
    out.push(v === null || v === undefined ? { time: l.t[i]! } : { time: l.t[i]!, value: v });
  }
  return out;
}

/** Contiguous runs of valued points. Step lines are drawn one series per run: lightweight-charts
 *  connects a stepped line across gaps, while a trade's stop/target must stop with the trade. */
export function splitRuns(points: { time: number; value?: number }[]): { time: number; value: number }[][] {
  const runs: { time: number; value: number }[][] = [];
  let cur: { time: number; value: number }[] = [];
  for (const p of points) {
    if (p.value === undefined) {
      if (cur.length) runs.push(cur);
      cur = [];
    } else cur.push({ time: p.time, value: p.value });
  }
  if (cur.length) runs.push(cur);
  return runs;
}
