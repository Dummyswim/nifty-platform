import { create } from "zustand";

/** The pane the pointer is over (`from`) and its crosshair time; the other panes follow it. */
export interface Hover { t: number | null; from: number }

/** A pane's "pointer left" (t = null) only resets the hover when that pane still owns it:
 *  the leave of pane X can arrive after the first move in pane Y. */
export function nextHover(h: Hover, t: number | null, from: number): Hover {
  return t === null && h.from !== from ? h : { t, from };
}

/** Subscribed by ChartView directly (not via React state), so pointer moves re-render no pane. */
export const useHover = create<Hover>(() => ({ t: null, from: -1 }));
