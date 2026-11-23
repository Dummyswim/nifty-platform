import type { TradeOut } from "../api/schemas";

const IST_DAY = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" });

export interface Curves {
  t: number[]; // exit time, epoch s
  equity: number[]; // cumulative net_pts
  drawdown: number[]; // <= 0, peak-to-trough
  sessions: { day: string; pnl: number }[];
}

export function curves(trades: TradeOut[]): Curves {
  const ts = [...trades].sort((a, b) => Date.parse(a.exit_time) - Date.parse(b.exit_time));
  const out: Curves = { t: [], equity: [], drawdown: [], sessions: [] };
  let cum = 0;
  let peak = 0;
  const per = new Map<string, number>();
  for (const t of ts) {
    cum += t.net_pts;
    peak = Math.max(peak, cum);
    out.t.push(Math.floor(Date.parse(t.exit_time) / 1000));
    out.equity.push(cum);
    out.drawdown.push(cum - peak);
    const day = IST_DAY.format(new Date(t.exit_time));
    per.set(day, (per.get(day) ?? 0) + t.net_pts);
  }
  out.sessions = [...per.entries()].map(([day, pnl]) => ({ day, pnl })).sort((a, b) => (a.day < b.day ? -1 : 1));
  return out;
}

export interface Bin { lo: number; hi: number; n: number }
/** Histogram of per-session P&L with `bins` equal-width bins. */
export function histogram(values: number[], bins = 8): Bin[] {
  if (values.length === 0) return [];
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (lo === hi) return [{ lo, hi, n: values.length }];
  const w = (hi - lo) / bins;
  const out: Bin[] = Array.from({ length: bins }, (_, i) => ({ lo: lo + i * w, hi: lo + (i + 1) * w, n: 0 }));
  for (const v of values) out[Math.min(bins - 1, Math.floor((v - lo) / w))]!.n++;
  return out;
}

export function fmtMetric(v: number | null | undefined, nd = 2, na = "n/a"): string {
  return v === null || v === undefined ? na : v.toFixed(nd);
}
