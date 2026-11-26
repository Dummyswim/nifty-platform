import type { PaneState } from "./layout";

const MON = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

/** "NIFTY 29DEC 25800 CE" from an ISO expiry date (YYYY-MM-DD). */
export function contractLabel(underlying: string, expiry: string, strike: number, type: "CE" | "PE"): string {
  const [, m, d] = expiry.split("-");
  return `${underlying} ${d}${MON[Number(m) - 1] ?? "?"} ${strike} ${type}`;
}

/** Note shown in a pane: option contracts are recorded by the live collector only. */
export function paneNote(kind: PaneState["kind"], bars: number): string | null {
  return kind === "option" && bars === 0 ? "no recorded bars" : null;
}
