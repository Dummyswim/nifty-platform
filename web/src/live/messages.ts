/** Live WebSocket protocol (docs/STATE.md): client subscribes, server sends snapshot first. */
import { type Cols, emptyCols } from "../chart/geometry";

export interface LiveBars {
  t: number[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
  final: boolean[];
}
export type CollectorState = "live" | "stale" | "disconnected" | "auth_expired" | "down";
export interface StatusMsg {
  type: "status";
  state: CollectorState;
  detail?: string;
  last_tick_age_s?: number | null;
}
export type ServerMsg =
  | { type: "snapshot"; instrument_id: string; timeframe: string; volume_kind: string; bars: LiveBars; cursor: number | null }
  | { type: "bar"; bars: LiveBars; provisional?: false }
  | { type: "bar"; provisional: true; bar: { t: number; o: number; h: number; l: number; c: number; v: number; final: boolean } }
  | { type: "event"; engine_id: string; event: unknown }
  | { type: "panel"; engine_id: string; run_id: string; panel: unknown; t: number }
  | StatusMsg;

/** Replace-by-time merge of live bars into the chart data: a resubscribe or a re-sent forming
 *  bucket never duplicates a candle. Result is strictly ascending by time. */
export function mergeLive(cols: Cols, b: LiveBars): Cols {
  const idx = new Map<number, number>();
  cols.t.forEach((t, i) => idx.set(t, i));
  const out: Cols = { t: [...cols.t], o: [...cols.o], h: [...cols.h], l: [...cols.l], c: [...cols.c], v: [...cols.v] };
  const fresh: number[] = [];
  b.t.forEach((t, k) => {
    const at = idx.get(t);
    if (at === undefined) {
      fresh.push(k);
      return;
    }
    out.o[at] = b.o[k]!;
    out.h[at] = b.h[k]!;
    out.l[at] = b.l[k]!;
    out.c[at] = b.c[k]!;
    out.v[at] = b.v[k]!;
  });
  for (const k of fresh) {
    out.t.push(b.t[k]!);
    out.o.push(b.o[k]!);
    out.h.push(b.h[k]!);
    out.l.push(b.l[k]!);
    out.c.push(b.c[k]!);
    out.v.push(b.v[k]!);
  }
  if (fresh.length === 0) return out;
  const order = out.t.map((_, i) => i).sort((a, c) => out.t[a]! - out.t[c]!);
  const sorted = emptyCols();
  for (const i of order) {
    sorted.t.push(out.t[i]!);
    sorted.o.push(out.o[i]!);
    sorted.h.push(out.h[i]!);
    sorted.l.push(out.l[i]!);
    sorted.c.push(out.c[i]!);
    sorted.v.push(out.v[i]!);
  }
  return sorted;
}

export const oneBar = (b: { t: number; o: number; h: number; l: number; c: number; v: number; final: boolean }): LiveBars => ({
  t: [b.t], o: [b.o], h: [b.h], l: [b.l], c: [b.c], v: [b.v], final: [b.final],
});

export interface Banner {
  level: "ok" | "warn" | "error";
  text: string;
  connectKite: boolean;
}

/** What the banner says for the collector state and the browser's socket state. */
export function banner(state: CollectorState | null, socket: "connecting" | "open" | "closed"): Banner {
  if (socket !== "open") return { level: "warn", text: socket === "connecting" ? "Connecting to live feed…" : "Live feed disconnected, retrying…", connectKite: false };
  switch (state) {
    case "live": return { level: "ok", text: "Live", connectKite: false };
    case "stale": return { level: "warn", text: "Stale: no ticks received recently", connectKite: false };
    case "disconnected": return { level: "warn", text: "Collector is disconnected from the market feed", connectKite: false };
    case "auth_expired": return { level: "error", text: "Kite session expired", connectKite: true };
    case "down": return { level: "warn", text: "Collector is not running (start `make live` or `make demo`)", connectKite: false };
    default: return { level: "warn", text: "Waiting for status…", connectKite: false };
  }
}

/** Reconnect delay: exponential, capped, with jitter in [0.5x, 1x]. `rand` is injectable for tests. */
export const backoffMs = (attempt: number, rand: () => number = Math.random): number =>
  Math.round(Math.min(15_000, 1000 * 2 ** attempt) * (0.5 + rand() / 2));

/** Provisional candles are drawn hollow with a coloured outline. */
export function candleStyle(up: boolean, provisional: boolean): { color?: string; borderColor?: string; wickColor?: string } {
  const c = up ? "#26a69a" : "#ef5350";
  return provisional ? { color: "rgba(0,0,0,0)", borderColor: c, wickColor: c } : {};
}
