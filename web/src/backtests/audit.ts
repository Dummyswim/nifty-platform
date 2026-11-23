import type { AuditOut } from "../api/schemas";
import type { El } from "../overlay/pick";

const sec = (iso: string) => Math.floor(Date.parse(iso) / 1000);

/** Entry / stop / target / exit lines and markers for one audited trade (drawn by the chart). */
export function auditOverlays(a: AuditOut): El[] {
  const t = a.trade;
  const from = sec(t.signal_bar_start ?? t.entry_time);
  const to = sec(t.exit_time);
  const base = { ver: 0, deleted: false, avail: 0, t0: from, t1: to, p1: null, text: null, meta: {} };
  const line = (id: string, price: number | null | undefined, role: string, text: string): El[] =>
    price === null || price === undefined
      ? []
      : [{ ...base, id: `audit:${id}`, kind: "line", p0: price, p1: price, text, style: { role, dashed: id !== "entry" } }];
  const buy = t.side === "long";
  return [
    ...line("entry", a.levels.entry_px_pts, buy ? "bull" : "bear", "entry"),
    ...line("stop", a.levels.stop_px_pts, "bear", "stop"),
    ...line("target", a.levels.target_px_pts, "bull", "target"),
    ...line("exit", a.levels.exit_px_pts, "info", a.exit_reason),
    { ...base, id: "audit:entry:entry", kind: "marker", t0: sec(t.entry_time), t1: null, p0: t.entry_px, text: buy ? "BUY" : "SELL", style: { role: buy ? "bull" : "bear" } },
    { ...base, id: "audit:exit:marker", kind: "marker", t0: to, t1: null, p0: t.exit_px, text: a.exit_reason, style: { role: "info" } },
  ];
}
