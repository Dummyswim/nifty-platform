import type { TradeOut } from "../api/schemas";

export type SortKey = "entry_time" | "exit_time" | "net_pts" | "r_multiple" | "bars_held" | "exit_reason" | "side";
export interface Filters {
  side: "all" | "long" | "short";
  reason: string; // "all" or an exit reason
  result: "all" | "win" | "loss";
}
export const NO_FILTER: Filters = { side: "all", reason: "all", result: "all" };

export function filterTrades(ts: TradeOut[], f: Filters): TradeOut[] {
  return ts.filter(
    (t) =>
      (f.side === "all" || t.side === f.side) &&
      (f.reason === "all" || t.exit_reason === f.reason) &&
      (f.result === "all" || (f.result === "win" ? t.net_pts > 0 : t.net_pts < 0)),
  );
}

export function sortTrades(ts: TradeOut[], key: SortKey, dir: 1 | -1): TradeOut[] {
  const val = (t: TradeOut): number | string => (t[key] ?? 0) as number | string;
  return [...ts].sort((a, b) => {
    const x = val(a);
    const y = val(b);
    return (x < y ? -1 : x > y ? 1 : 0) * dir;
  });
}

export const reasonsOf = (ts: TradeOut[]): string[] => [...new Set(ts.map((t) => t.exit_reason))].sort();
