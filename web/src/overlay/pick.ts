import type { components } from "../api/types";

type OverlayElement = components["schemas"]["OverlayElement"];

/** OverlayElement with times as UTC epoch seconds. */
export interface El {
  id: string;
  ver: number;
  deleted: boolean;
  avail: number;
  kind: OverlayElement["kind"];
  t0: number;
  t1: number | null;
  p0: number | null;
  p1: number | null;
  style: Record<string, unknown>;
  text: string | null;
  meta: Record<string, unknown>;
}

const sec = (iso: string): number => Math.floor(Date.parse(iso) / 1000);

export function toEl(o: OverlayElement): El {
  return {
    id: o.id,
    ver: o.ver,
    deleted: o.deleted,
    avail: sec(o.avail_at_utc ?? o.t0),
    kind: o.kind,
    t0: sec(o.t0),
    t1: o.t1 ? sec(o.t1) : null,
    p0: o.p0 ?? null,
    p1: o.p1 ?? null,
    style: o.style ?? {},
    text: o.text ?? null,
    meta: o.meta ?? {},
  };
}

/** Per id the latest `ver` with avail <= cursor; deleted ones are dropped; `t1 = null` extends to the
 *  cursor (or `end`, the last bar time, when there is no cursor). Never recomputes anything. */
export function pickOverlays(els: El[], cursor: number | null, end: number): El[] {
  const best = new Map<string, El>();
  for (const e of els) {
    if (cursor !== null && e.avail > cursor) continue;
    const cur = best.get(e.id);
    if (!cur || e.ver >= cur.ver) best.set(e.id, e);
  }
  const edge = cursor ?? end;
  return [...best.values()]
    .filter((e) => !e.deleted)
    .map((e) => (e.t1 === null ? { ...e, t1: Math.max(edge, e.t0) } : e));
}

// ---- role tokens -> theme colours ------------------------------------------------------------
export const ROLE_COLOR: Record<string, string> = {
  demand: "#26a69a",
  supply: "#ef5350",
  neutral: "#9aa4b2",
  bull: "#26a69a",
  bear: "#ef5350",
  info: "#4c8dff",
  warn: "#f5a623",
  vwap: "#f59e0b",
  buy: "#26a69a",
  sell: "#ef5350",
};

/** `overrides` are an engine's `ui.color_<role>` settings. */
export function roleColor(role: unknown, overrides: Record<string, string> = {}): string {
  const r = typeof role === "string" ? role : "neutral";
  return overrides[r] ?? ROLE_COLOR[r] ?? ROLE_COLOR.neutral!;
}

export type ZoneStatus = "active" | "mitigated" | "projected";
export interface ZoneStyle {
  fillAlpha: number;
  dashed: boolean;
}
export function zoneStyle(meta: Record<string, unknown>): ZoneStyle {
  const s = (meta.status as ZoneStatus | undefined) ?? "active";
  if (s === "mitigated") return { fillAlpha: 0.07, dashed: true };
  if (s === "projected") return { fillAlpha: 0, dashed: true };
  return { fillAlpha: 0.18, dashed: false };
}
