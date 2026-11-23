/** Pure chart maths: time <-> logical index, hit-testing, moving, merging pages, IST formatting. */

export const TFS = ["1m", "3m", "5m", "10m", "15m", "30m", "1h", "1d"] as const;
export type Tf = (typeof TFS)[number];
export const TF_LABEL: Record<Tf, string> = {
  "1m": "1m", "3m": "3m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m", "1h": "1H", "1d": "1D",
};

export interface Cols {
  t: number[];
  o: number[];
  h: number[];
  l: number[];
  c: number[];
  v: number[];
}
export const emptyCols = (): Cols => ({ t: [], o: [], h: [], l: [], c: [], v: [] });

/** Older page + current data -> strictly ascending, unique times (current wins on a tie). */
export function mergeCols(older: Cols, cur: Cols): Cols {
  const out = emptyCols();
  const seen = new Set<number>();
  const take = (src: Cols) => {
    for (let i = 0; i < src.t.length; i++) {
      const ts = src.t[i]!;
      if (seen.has(ts)) continue;
      seen.add(ts);
      out.t.push(ts);
      out.o.push(src.o[i]!);
      out.h.push(src.h[i]!);
      out.l.push(src.l[i]!);
      out.c.push(src.c[i]!);
      out.v.push(src.v[i]!);
    }
  };
  take(cur);
  take(older);
  const idx = out.t.map((_, i) => i).sort((a, b) => out.t[a]! - out.t[b]!);
  const sorted = emptyCols();
  for (const i of idx) {
    sorted.t.push(out.t[i]!);
    sorted.o.push(out.o[i]!);
    sorted.h.push(out.h[i]!);
    sorted.l.push(out.l[i]!);
    sorted.c.push(out.c[i]!);
    sorted.v.push(out.v[i]!);
  }
  return sorted;
}

/** Index of the last element <= t (-1 when t precedes all). */
function floorIndex(times: number[], t: number): number {
  let lo = 0;
  let hi = times.length - 1;
  let ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid]! <= t) {
      ans = mid;
      lo = mid + 1;
    } else hi = mid - 1;
  }
  return ans;
}

/** Fractional bar index of time t. Times between bars interpolate; outside the data they
 *  extrapolate with the nearest bar step. A 1m drawing therefore keeps its place on a 5m chart. */
export function timeToLogical(times: number[], t: number): number | null {
  const n = times.length;
  if (n === 0) return null;
  if (n === 1) return (t - times[0]!) / 60;
  const i = floorIndex(times, t);
  if (i < 0) return (t - times[0]!) / (times[1]! - times[0]!);
  if (i >= n - 1) return n - 1 + (t - times[n - 1]!) / (times[n - 1]! - times[n - 2]!);
  return i + (t - times[i]!) / (times[i + 1]! - times[i]!);
}

export function logicalToTime(times: number[], x: number): number | null {
  const n = times.length;
  if (n === 0) return null;
  if (n === 1) return Math.round(times[0]! + x * 60);
  if (x < 0) return Math.round(times[0]! + x * (times[1]! - times[0]!));
  if (x >= n - 1) return Math.round(times[n - 1]! + (x - (n - 1)) * (times[n - 1]! - times[n - 2]!));
  const i = Math.floor(x);
  return Math.round(times[i]! + (x - i) * (times[i + 1]! - times[i]!));
}

export interface Pt {
  x: number;
  y: number;
}
export interface TP {
  t: number;
  p: number;
}

export function distToSegment(p: Pt, a: Pt, b: Pt): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const u = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
  return Math.hypot(p.x - (a.x + u * dx), p.y - (a.y + u * dy));
}

/** A drawing in pixel space. hline ignores x; text has a box. */
export type Shape =
  | { kind: "trendline"; a: Pt; b: Pt }
  | { kind: "hline"; y: number }
  | { kind: "rect"; a: Pt; b: Pt }
  | { kind: "text"; a: Pt; w: number; h: number };

export type Hit = "p0" | "p1" | "body";

export function hitTest(s: Shape, p: Pt, tol = 6): Hit | null {
  switch (s.kind) {
    case "hline":
      return Math.abs(p.y - s.y) <= tol ? "body" : null;
    case "trendline":
      if (Math.hypot(p.x - s.a.x, p.y - s.a.y) <= tol + 2) return "p0";
      if (Math.hypot(p.x - s.b.x, p.y - s.b.y) <= tol + 2) return "p1";
      return distToSegment(p, s.a, s.b) <= tol ? "body" : null;
    case "rect": {
      const x0 = Math.min(s.a.x, s.b.x);
      const x1 = Math.max(s.a.x, s.b.x);
      const y0 = Math.min(s.a.y, s.b.y);
      const y1 = Math.max(s.a.y, s.b.y);
      if (Math.hypot(p.x - s.a.x, p.y - s.a.y) <= tol + 2) return "p0";
      if (Math.hypot(p.x - s.b.x, p.y - s.b.y) <= tol + 2) return "p1";
      const inside = p.x >= x0 - tol && p.x <= x1 + tol && p.y >= y0 - tol && p.y <= y1 + tol;
      return inside ? "body" : null;
    }
    case "text":
      return p.x >= s.a.x && p.x <= s.a.x + s.w && p.y >= s.a.y - s.h && p.y <= s.a.y ? "body" : null;
  }
}

/** Move whole drawing (`body`) or one handle by a delta in (logical index, price). */
export function movePoints(
  times: number[],
  pts: TP[],
  hit: Hit,
  dLogical: number,
  dPrice: number,
): TP[] {
  return pts.map((pt, i) => {
    if (hit === "p0" && i !== 0) return pt;
    if (hit === "p1" && i !== 1) return pt;
    const lg = timeToLogical(times, pt.t);
    const t = lg === null ? null : logicalToTime(times, lg + dLogical);
    return { t: t ?? pt.t, p: pt.p + dPrice };
  });
}

// ---- IST axis (times stay UTC epoch seconds everywhere else) --------------------------------
const FMT = {
  time: new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", hour12: false }),
  day: new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short" }),
  full: new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Kolkata", day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  }),
  year: new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", year: "numeric" }),
};
export const fmtIst = (t: number, kind: keyof typeof FMT = "full"): string => FMT[kind].format(new Date(t * 1000));

/** lightweight-charts TickMarkType: 0 year, 1 month, 2 day, 3 time, 4 time with seconds. */
export function tickLabel(t: number, type: number): string {
  if (type === 0) return fmtIst(t, "year");
  if (type === 1 || type === 2) return fmtIst(t, "day");
  return fmtIst(t, "time");
}
