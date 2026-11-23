/** Replay maths (pure). The cursor is the instant "now" of the replay, UTC epoch seconds; null = the
 *  end of the data (live view). Outputs are revealed by availability, never recomputed. */
import type { Tf } from "../chart/geometry";

export const TF_SEC: Record<Tf, number> = {
  "1m": 60, "3m": 180, "5m": 300, "10m": 600, "15m": 900, "30m": 1800, "1h": 3600, "1d": 86400,
};
export const SPEEDS = [1, 5, 20, 100] as const;
export type Speed = (typeof SPEEDS)[number];

export const barEnd = (t: number, tf: Tf): number => t + TF_SEC[tf];

/** Number of bars finished by the cursor (bar end <= cursor). */
export function visibleCount(times: number[], tf: Tf, cursor: number | null): number {
  if (cursor === null) return times.length;
  const lim = cursor - TF_SEC[tf];
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid]! <= lim) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Step the cursor by whole bars. Past the last bar it returns null (end of data). */
export function stepCursor(times: number[], tf: Tf, cursor: number | null, dir: 1 | -1): number | null {
  const n = times.length;
  if (n === 0) return cursor;
  const shown = visibleCount(times, tf, cursor);
  const target = shown + dir; // number of bars to show after the step
  if (target >= n) return null;
  return barEnd(times[Math.max(1, target) - 1]!, tf);
}

/** Cursor that shows every bar up to and including the one containing t. */
export function jumpCursor(times: number[], tf: Tf, t: number): number | null {
  if (times.length === 0) return null;
  let idx = 0;
  for (let i = 0; i < times.length; i++) if (times[i]! <= t) idx = i;
  return idx >= times.length - 1 ? null : barEnd(times[idx]!, tf);
}

export const tickMs = (speed: Speed): number => 1000 / speed;

export function availableBy<T>(items: T[], avail: (x: T) => number, cursor: number | null): T[] {
  return cursor === null ? items : items.filter((x) => avail(x) <= cursor);
}

/** "2026-11-16T10:35" typed as IST -> epoch seconds. */
export const istToEpoch = (local: string): number => Math.floor(Date.parse(`${local}:00+05:30`) / 1000);
