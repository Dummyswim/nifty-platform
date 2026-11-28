import { describe, expect, it } from "vitest";
import type { ContextState } from "../api/schemas";
import { collapsedLine, fmtOi, moveLine, ruleLine, vixLine, wallsLine } from "./format";

const st = (o: Partial<ContextState>) => ({ t: 0, bias: "NONE", candidate: "NONE", ce: {}, pe: {}, flags: [], ...o }) as unknown as ContextState;

describe("fmtOi", () => {
  it("millions with 1 dp", () => {
    expect(fmtOi(6_100_000)).toBe("6.1M");
    expect(fmtOi(1_000_000)).toBe("1.0M");
    expect(fmtOi(12_345_678)).toBe("12.3M");
  });
  it("under 1M -> integer K", () => {
    expect(fmtOi(482_400)).toBe("482K");
    expect(fmtOi(999_400)).toBe("999K");
    expect(fmtOi(999_600)).toBe("1.0M"); // would round to 1000K
  });
});

describe("wallsLine", () => {
  it("both sides with thousands separators", () =>
    expect(wallsLine({ strike: 26300, oi: 6_100_000, edge: false }, { strike: 25900, oi: 4_820_000, edge: false })).toBe("Walls: CE 26,300 (6.1M) · PE 25,900 (4.8M)"));
  it("edge marks the wall as maybe beyond the recorded window", () =>
    expect(wallsLine({ strike: 26300, oi: 6_100_000, edge: true }, { strike: 25700, oi: 900_000, edge: true })).toBe("Walls: CE ≥26,300 (6.1M) · PE ≤25,700 (900K)"));
  it("a missing side is left out; none -> null", () => {
    expect(wallsLine(null, { strike: 25900, oi: 4_820_000, edge: false })).toBe("Walls: PE 25,900 (4.8M)");
    expect(wallsLine(null, undefined)).toBeNull();
  });
});

describe("moveLine", () => {
  it("move, expected, used and room", () =>
    expect(moveLine(st({ day_move_pts: -160.4, exp_move_pts: 275.2, used_pct: 58.3, room_left_pts: 114.8, late: false }))).toBe("Move −160 / ±275 · 58 % · room 115"));
  it("late and negative room", () =>
    expect(moveLine(st({ day_move_pts: 300, exp_move_pts: 275, used_pct: 109.1, room_left_pts: -25, late: true }))).toBe("Move 300 / ±275 · 109 % · room −25 · LATE"));
  it("missing inputs -> null", () => expect(moveLine(st({ day_move_pts: -160 }))).toBeNull());
});

describe("vixLine", () => {
  it("VIX, rank, HIGH and both side IVs", () =>
    expect(vixLine(st({ vix: 15, vix_rank: 99.6, vix_high: true, ce: { iv: 14.44, verdict: "FAIR" }, pe: { iv: 13.96, verdict: "CHEAP" } }))).toBe("VIX 15.0 P100 HIGH · CE 14.4 FAIR · PE 14.0 CHEAP"));
  it("no rank, one side", () => expect(vixLine(st({ vix: 15.04, ce: { iv: 14.4 }, pe: {} }))).toBe("VIX 15.0 · CE 14.4"));
  it("nothing -> null", () => expect(vixLine(st({ ce: {}, pe: {} }))).toBeNull());
});

describe("ruleLine", () => {
  it("call writing, bearish since", () =>
    expect(ruleLine("iv", st({ w_day: -0.883, bias: "BEARISH", bias_since: Date.UTC(2026, 10, 27, 4, 55) / 1000 }))).toBe("OI+IV  CALL −0.88 ▼ BEARISH · buy PE  10:25"));
  it("put writing, bullish", () =>
    expect(ruleLine("oi", st({ w_day: 0.5, bias: "BULLISH", bias_since: Date.UTC(2026, 10, 27, 5, 36) / 1000 }))).toBe("Raw OI PUT 0.50 ▲ BULLISH · buy CE  11:06"));
  it("no writing, no bias", () => expect(ruleLine("oi", st({ w_day: 0 }))).toBe("Raw OI — 0.00 NO BIAS"));
  it("no score", () => expect(ruleLine("iv", st({}))).toBe("OI+IV  NO BIAS"));
});

describe("collapsedLine", () => {
  it("both rules and room", () =>
    expect(collapsedLine([["iv", "BEARISH"], ["oi", "BEARISH"]], 115.4, false)).toBe("▼ BEAR (IV) · ▼ BEAR (OI) · room 115"));
  it("bull / none, late", () =>
    expect(collapsedLine([["iv", "BULLISH"], ["oi", "NONE"]], -12, true)).toBe("▲ BULL (IV) · – NONE (OI) · room −12 · LATE"));
  it("a disabled rule is left out; no room -> room n/a", () =>
    expect(collapsedLine([["oi", "BEARISH"]], null, null)).toBe("▼ BEAR (OI) · room n/a"));
});
