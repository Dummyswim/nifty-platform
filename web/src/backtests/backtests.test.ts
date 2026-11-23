import { expect, test } from "vitest";
import type { AuditOut, TradeOut } from "../api/schemas";
import { auditOverlays } from "./audit";
import { curves, fmtMetric, histogram } from "./series";
import { NO_FILTER, filterTrades, reasonsOf, sortTrades } from "./tradeTable";

const tr = (id: string, side: "long" | "short", net: number, reason: string, exit: string): TradeOut =>
  ({ trade_id: id, side, net_pts: net, exit_reason: reason, entry_time: exit, exit_time: exit, entry_px: 1, exit_px: 2, bars_held: 1, r_multiple: net / 10 }) as TradeOut;
const T = [
  tr("a", "long", 10, "TP", "2026-11-02T05:00:00Z"),
  tr("b", "short", -5, "SL", "2026-11-02T06:00:00Z"),
  tr("c", "long", -3, "SL", "2026-11-03T05:00:00Z"),
  tr("d", "long", 4, "EOD", "2026-11-03T09:00:00Z"),
];

test("filters by side, reason and result", () => {
  expect(filterTrades(T, { ...NO_FILTER, side: "long" }).map((t) => t.trade_id)).toEqual(["a", "c", "d"]);
  expect(filterTrades(T, { ...NO_FILTER, reason: "SL" }).map((t) => t.trade_id)).toEqual(["b", "c"]);
  expect(filterTrades(T, { ...NO_FILTER, result: "win" }).map((t) => t.trade_id)).toEqual(["a", "d"]);
  expect(filterTrades(T, { side: "long", reason: "SL", result: "loss" }).map((t) => t.trade_id)).toEqual(["c"]);
  expect(reasonsOf(T)).toEqual(["EOD", "SL", "TP"]);
});

test("sorts both ways without mutating", () => {
  expect(sortTrades(T, "net_pts", 1).map((t) => t.trade_id)).toEqual(["b", "c", "d", "a"]);
  expect(sortTrades(T, "net_pts", -1)[0]!.trade_id).toBe("a");
  expect(T[0]!.trade_id).toBe("a");
});

test("equity, drawdown and per-session P&L (IST days)", () => {
  const c = curves(T);
  expect(c.equity).toEqual([10, 5, 2, 6]);
  expect(c.drawdown).toEqual([0, -5, -8, -4]);
  expect(c.sessions).toEqual([{ day: "2026-11-02", pnl: 5 }, { day: "2026-11-03", pnl: 1 }]);
});

test("histogram keeps every value", () => {
  const h = histogram([1, 2, 3, 10], 3);
  expect(h.reduce((s, b) => s + b.n, 0)).toBe(4);
  expect(histogram([5, 5], 3)).toEqual([{ lo: 5, hi: 5, n: 2 }]);
  expect(histogram([])).toEqual([]);
});

test("null profit factor reads n/a", () => {
  expect(fmtMetric(null, 2, "n/a (no losses)")).toBe("n/a (no losses)");
  expect(fmtMetric(1.234)).toBe("1.23");
});

test("audit overlays: entry/stop/target/exit lines + markers", () => {
  const a = {
    trade: { ...T[0]!, signal_bar_start: "2026-11-02T04:55:00Z", entry_time: "2026-11-02T05:00:00Z", entry_px: 100, exit_px: 110 },
    levels: { entry_px_pts: 100, stop_px_pts: 95, target_px_pts: 110, exit_px_pts: 110 },
    exit_reason: "TP",
  } as unknown as AuditOut;
  const els = auditOverlays(a);
  expect(els.filter((e) => e.kind === "line").map((e) => e.id)).toEqual(["audit:entry", "audit:stop", "audit:target", "audit:exit"]);
  expect(els.filter((e) => e.kind === "marker")).toHaveLength(2);
  expect(auditOverlays({ ...a, levels: { entry_px_pts: 100 } } as unknown as AuditOut).filter((e) => e.kind === "line")).toHaveLength(1);
});
