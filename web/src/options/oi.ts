/** Pure helpers for the options page. */
import type { ChainOut, ChainSide } from "../api/schemas";

export type StrikeType = "Deep ITM" | "ITM" | "ATM" | "OTM" | "Deep OTM";
export type OptionType = "CE" | "PE";
export const STRIKE_TYPES: StrikeType[] = ["Deep ITM", "ITM", "ATM", "OTM", "Deep OTM"];
export const EXPIRY_KINDS = ["current weekly", "next weekly", "monthly"] as const;

/** The strike a (strike type, option type) selection resolves to in this chain, or null. */
export function pickedStrike(chain: ChainOut | undefined, st: StrikeType, ot: OptionType): number | null {
  return chain?.picks?.[st]?.[ot] ?? null;
}

export function fmt(x: number | null | undefined, nd = 2): string {
  return x === null || x === undefined ? "—" : x.toFixed(nd);
}

/** Honest one-line state of one side of a strike (never an error for missing data). */
export function sideState(s: ChainSide | null | undefined): string {
  if (!s) return "not listed";
  if (!s.recorded) return "not recorded";
  if (s.last === null || s.last === undefined) return "no quote";
  return s.age_s !== null && s.age_s !== undefined && s.age_s > 60 ? `stale (${Math.round(s.age_s)} s)` : "quote";
}

export function greeksText(s: ChainSide | null | undefined): string {
  if (!s) return "—";
  return s.greeks === "computed" ? "computed" : (s.greeks_note ?? "n/a");
}

export function ageText(sec: number | null | undefined): string {
  if (sec === null || sec === undefined) return "—";
  if (sec < 90) return `${Math.round(sec)} s`;
  if (sec < 5400) return `${Math.round(sec / 60)} min`;
  return `${(sec / 3600).toFixed(1)} h`;
}
