import type { ContextState } from "../api/schemas";

/** State shown at the replay cursor: null cursor -> the latest; else the last state with t <= cursor. */
export function pickState(series: ContextState[], cursor: number | null): ContextState | null {
  if (cursor === null) return series[series.length - 1] ?? null;
  let found: ContextState | null = null;
  for (const s of series) {
    if (s.t > cursor) break;
    found = s;
  }
  return found;
}
