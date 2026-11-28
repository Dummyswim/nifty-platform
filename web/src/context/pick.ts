import { ApiError } from "../api/client";
import type { ContextOut, ContextState } from "../api/schemas";

const BAR_S = 60;

/** State shown at the replay cursor ("now"): null cursor -> the latest; else the last state whose
 * bar has closed (t + 60 <= cursor), since a state keyed by bar start uses data up to its end. */
export function pickState(series: ContextState[], cursor: number | null): ContextState | null {
  if (cursor === null) return series[series.length - 1] ?? null;
  let found: ContextState | null = null;
  for (const s of series) {
    if (s.t + BAR_S > cursor) break;
    found = s;
  }
  return found;
}

/** What the box shows: the state at the cursor, or one line (`note`) instead of its rows. */
export function boxView(
  data: ContextOut | undefined,
  cursor: number | null,
  error: unknown,
): { state: ContextState | null; note: string | null; flags: string[] } {
  if (error) {
    const why = error instanceof ApiError ? String(error.status) : error instanceof Error ? error.message : String(error);
    return { state: null, note: `n/a: context unavailable (${why})`, flags: [] };
  }
  const s = data ? pickState(data.series, cursor) : null;
  if (!s) return { state: null, note: data?.series.length ? "no data yet" : (data?.notes[0] ?? "no data"), flags: [] };
  const note = s.na_reason ? (s.na_reason.includes("n/a") ? s.na_reason : `n/a: ${s.na_reason}`) : null;
  return { state: s, note, flags: s.flags };
}

const istDate = (t: number) => new Date((t + 19800) * 1000).toISOString().slice(0, 10);

/** The session date to ask for: Live none (the server picks today); History the cursor's IST date,
 * else that of the pane's last bar, else none (the server picks the last session). */
export function contextDate(live: boolean, cursor: number | null, lastBarT: number | null): string | undefined {
  if (live) return undefined;
  if (cursor !== null) return istDate(cursor);
  return lastBarT !== null ? istDate(lastBarT) : undefined;
}
