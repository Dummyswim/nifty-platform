import { describe, expect, it } from "vitest";
import type { LabelOut } from "../api/schemas";
import { type Ev, ciOption, eventsNear, labelOverlays, labelText } from "./view";

const T = (m: number) => new Date(Date.UTC(2026, 10, 2, 4, m)).toISOString();
const label = { signal_bar_start: T(10), side: "short", trade: { side: "short", entry_time: T(11), exit_time: T(15), entry_px: 100 } } as unknown as LabelOut;
const ev = (type: string, m: number, payload: Record<string, unknown> = {}) => ({ event_type: type, bar_start_utc: T(m), payload }) as unknown as Ev;

describe("research view", () => {
  it("labels by side, never claims confirmations", () => {
    expect(labelText("short")).toBe("BEARISH INDEX / PUT CANDIDATE");
    expect(labelText("long")).toBe("BULLISH INDEX / CALL CANDIDATE");
    expect(labelText("long")).not.toMatch(/confirmation/i);
  });
  it("selects events from 30 min before the signal to the exit", () => {
    const evs = [ev("research.watch", -40), ev("research.watch", -15), ev("research.exit", 15), ev("research.watch", 40)];
    expect(eventsNear(evs, label)).toHaveLength(2);
  });
  it("draws entry/stop/target lines and one marker per event", () => {
    const sig = T(10);
    const evs = [ev("research.armed", 5), ev("research.entry", 11, { signal_bar_start: sig, stop_px: 112, target_px: 90 }), ev("research.exit", 15, { outcome: "TARGET_FIRST" })];
    const o = labelOverlays(label, evs);
    expect(o.filter((x) => x.kind === "line").map((x) => x.text)).toEqual(["entry", "stop", "target"]);
    expect(o.filter((x) => x.kind === "marker").map((x) => x.text)).toEqual(["armed", "entry", "TARGET_FIRST"]);
  });
  it("CI option has one category per cell", () => {
    const s = { ci_lo: -1, ci_hi: 2, expectancy_pts: 0.5 };
    const cell = { variant: "a_b", experiment: 10, stats: { splits: { eval: s } } } as never;
    expect((ciOption([cell, cell]).yAxis as { data: string[] }).data).toHaveLength(2);
  });
});
