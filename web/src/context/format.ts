import type { ContextSide, ContextState } from "../api/schemas";
import type { ContextWriting } from "./useMarketContext";

type Wall = NonNullable<ContextState["call_wall"]>;

export const RULE_LABEL: Record<ContextWriting, string> = { iv: "OI+IV ", oi: "Raw OI" };

export const hhmm = (t: number) => new Date((t + 19800) * 1000).toISOString().slice(11, 16); // IST
/** Fixed decimals with a real minus sign. */
export const signed = (v: number, d: number) => (v < 0 && Number(Math.abs(v).toFixed(d)) !== 0 ? "−" : "") + Math.abs(v).toFixed(d);
const int = (v: number) => signed(Math.round(v), 0);

/** OI as millions with 1 dp ("6.1M"), under 1M as integer thousands ("482K"). */
export function fmtOi(oi: number): string {
  return Math.round(oi / 1e3) >= 1000 ? `${(oi / 1e6).toFixed(1)}M` : `${Math.round(oi / 1e3)}K`;
}

const wall = (name: "CE" | "PE", w: Wall) =>
  `${name} ${w.edge ? (name === "CE" ? "≥" : "≤") : ""}${w.strike.toLocaleString("en-US", { maximumFractionDigits: 2 })} (${fmtOi(w.oi)})`;

/** `Walls: CE 26,300 (6.1M) · PE 25,900 (4.8M)`; `≥` / `≤` when the wall is the outermost recorded strike. */
export function wallsLine(call: Wall | null | undefined, put: Wall | null | undefined): string | null {
  const parts = [call && wall("CE", call), put && wall("PE", put)].filter(Boolean);
  return parts.length ? `Walls: ${parts.join(" · ")}` : null;
}

/** `Move −160 / ±275 · 58 % · room 115` (`· LATE` when late). */
export function moveLine(s: ContextState): string | null {
  if (s.day_move_pts == null || s.exp_move_pts == null || s.used_pct == null || s.room_left_pts == null) return null;
  return `Move ${int(s.day_move_pts)} / ±${Math.round(s.exp_move_pts)} · ${Math.round(s.used_pct)} % · room ${int(s.room_left_pts)}${s.late ? " · LATE" : ""}`;
}

const side = (name: string, s: ContextSide) => `${name} ${s.iv!.toFixed(1)}${s.verdict ? ` ${s.verdict}` : ""}`;

/** `VIX 15.0 P100 HIGH · CE 14.4 FAIR · PE 14.0 CHEAP`. */
export function vixLine(s: ContextState): string | null {
  const parts: string[] = [];
  if (s.vix != null) parts.push(`VIX ${s.vix.toFixed(1)}${s.vix_rank != null ? ` P${Math.round(s.vix_rank)}` : ""}${s.vix_high ? " HIGH" : ""}`);
  if (s.ce.iv != null) parts.push(side("CE", s.ce));
  if (s.pe.iv != null) parts.push(side("PE", s.pe));
  return parts.length ? parts.join(" · ") : null;
}

/** `OI+IV  CALL −0.88 ▼ BEARISH · buy PE  10:25`; `NO BIAS` when none. */
export function ruleLine(writing: ContextWriting, s: ContextState): string {
  const parts = [RULE_LABEL[writing]];
  if (s.w_day != null) parts.push(`${s.w_day < 0 ? "CALL" : s.w_day > 0 ? "PUT" : "—"} ${signed(s.w_day, 2)}`);
  const since = s.bias_since != null ? `  ${hhmm(s.bias_since)}` : "";
  if (s.bias === "BEARISH") parts.push(`▼ BEARISH · buy PE${since}`);
  else if (s.bias === "BULLISH") parts.push(`▲ BULLISH · buy CE${since}`);
  else parts.push("NO BIAS");
  return parts.join(" ");
}

const SHORT: Record<string, string> = { BEARISH: "▼ BEAR", BULLISH: "▲ BULL" };

/** One-line summary: `▼ BEAR (IV) · ▼ BEAR (OI) · room 115` (enabled rules only; `· LATE` when late). */
export function collapsedLine(rules: [ContextWriting, string][], room: number | null | undefined, late: boolean | null | undefined): string {
  const parts = rules.map(([w, bias]) => `${SHORT[bias] ?? "– NONE"} (${w.toUpperCase()})`);
  parts.push(room != null ? `room ${int(room)}` : "room n/a");
  return parts.join(" · ") + (late ? " · LATE" : "");
}
