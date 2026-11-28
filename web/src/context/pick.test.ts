import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import type { ContextOut, ContextState } from "../api/schemas";
import { boxView, contextDate, pickState } from "./pick";

const st = (t: number) => ({ t, bias: "NONE", candidate: "NONE", ce: {}, pe: {}, flags: [] }) as unknown as ContextState;
const series = [st(100), st(160), st(220)];

// A state keyed by bar start t uses data up to t + 60: it is available once the bar has closed.
describe("pickState", () => {
  it("null cursor -> last state", () => expect(pickState(series, null)?.t).toBe(220));
  it("cursor 160 -> the bar that closed at 160 (t=100)", () => expect(pickState(series, 160)?.t).toBe(100));
  it("cursor 220 -> t=160", () => expect(pickState(series, 220)?.t).toBe(160));
  it("cursor mid-bar -> the last closed bar", () => expect(pickState(series, 200)?.t).toBe(100));
  it("cursor exactly on a bar end -> the bar that just closed", () => expect(pickState(series, 280)?.t).toBe(220));
  it("cursor before the first bar closes -> null", () => {
    expect(pickState(series, 159)).toBeNull();
    expect(pickState(series, 99)).toBeNull();
  });
  it("empty series -> null", () => {
    expect(pickState([], null)).toBeNull();
    expect(pickState([], 100)).toBeNull();
  });
});

const out = (s: ContextState[], notes: string[] = []) => ({ series: s, notes }) as unknown as ContextOut;

describe("boxView", () => {
  it("query error -> one n/a line with the status", () => {
    const v = boxView(out(series), null, new ApiError(422, "invalid context prefs"));
    expect(v).toEqual({ state: null, note: "n/a: context unavailable (422)", flags: [] });
  });
  it("non-API error -> its message", () =>
    expect(boxView(undefined, null, new Error("Failed to fetch")).note).toBe("n/a: context unavailable (Failed to fetch)"));
  it("cursor before the first state of a non-empty series -> no data yet, not the notes", () =>
    expect(boxView(out(series, ["some note"]), 120, null).note).toBe("no data yet"));
  it("empty series -> notes[0], else no data", () => {
    expect(boxView(out([], ["no session data for 2026-11-28"]), null, null).note).toBe("no session data for 2026-11-28");
    expect(boxView(out([]), null, null).note).toBe("no data");
    expect(boxView(undefined, null, null).note).toBe("no data");
  });
  it("na_reason -> n/a line; state flags pass through for that minute only", () => {
    const a = { ...st(100), flags: ["expiry day: next weekly"], na_reason: "no VIX data" } as unknown as ContextState;
    const b = { ...st(160), flags: [] } as unknown as ContextState;
    expect(boxView(out([a, b]), 160, null)).toEqual({ state: a, note: "n/a: no VIX data", flags: ["expiry day: next weekly"] });
    expect(boxView(out([a, b]), 220, null)).toEqual({ state: b, note: null, flags: [] });
    const r = { ...st(100), na_reason: "IV n/a: set rate in Settings" } as unknown as ContextState;
    expect(boxView(out([r]), null, null).note).toBe("IV n/a: set rate in Settings");
  });
});

describe("contextDate", () => {
  const t = Date.UTC(2026, 10, 16, 9, 19) / 1000; // 14:49 IST
  it("cursor -> its IST date", () => expect(contextDate(false, Date.UTC(2026, 10, 16, 19, 0) / 1000, null)).toBe("2026-11-17")); // 00:30 IST
  it("History, no cursor -> the IST date of the pane's last bar", () => expect(contextDate(false, null, t)).toBe("2026-11-16"));
  it("History, no cursor, no bars yet -> omitted (server picks the last session)", () => expect(contextDate(false, null, null)).toBeUndefined());
  it("Live -> omitted", () => {
    expect(contextDate(true, null, t)).toBeUndefined();
    expect(contextDate(true, t, t)).toBeUndefined();
  });
});
