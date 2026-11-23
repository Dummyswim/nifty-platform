import { expect, test } from "vitest";
import { type Cols } from "../chart/geometry";
import { type LiveBars, backoffMs, banner, candleStyle, mergeLive, oneBar } from "./messages";

const cols = (t: number[]): Cols => ({ t, o: t.map(() => 1), h: t.map(() => 2), l: t.map(() => 0), c: t.map(() => 1.5), v: t.map(() => 0) });
const bars = (t: number[], c: number, final = true): LiveBars => ({ t, o: t.map(() => 1), h: t.map(() => 2), l: t.map(() => 0), c: t.map(() => c), v: t.map(() => 0), final: t.map(() => final) });

test("a re-sent bucket replaces, a new bar appends, never duplicates", () => {
  const a = mergeLive(cols([0, 60, 120]), bars([120], 9, false)); // forming bar updated
  expect(a.t).toEqual([0, 60, 120]);
  expect(a.c[2]).toBe(9);
  const b = mergeLive(a, bars([120, 180], 7)); // resubscribe replays 120 and adds 180
  expect(b.t).toEqual([0, 60, 120, 180]);
  expect(b.c.slice(2)).toEqual([7, 7]);
  expect(mergeLive(b, bars([180], 7)).t).toEqual(b.t); // idempotent
});

test("a snapshot into empty data and out-of-order input stay ascending", () => {
  expect(mergeLive({ t: [], o: [], h: [], l: [], c: [], v: [] }, bars([60, 0, 120], 1)).t).toEqual([0, 60, 120]);
});

test("one provisional bar message becomes a one-bar payload", () => {
  expect(oneBar({ t: 5, o: 1, h: 2, l: 0, c: 1, v: 0, final: false }).final).toEqual([false]);
});

test("banner covers connected, stale, auth expired (Connect Kite) and socket states", () => {
  expect(banner("live", "open")).toMatchObject({ level: "ok", text: "Live" });
  expect(banner("stale", "open").level).toBe("warn");
  expect(banner("auth_expired", "open")).toMatchObject({ level: "error", connectKite: true });
  expect(banner("down", "open").text).toContain("not running");
  expect(banner("live", "closed").text).toContain("disconnected");
  expect(banner(null, "connecting").text).toContain("Connecting");
});

test("backoff grows, is capped and jittered", () => {
  expect(backoffMs(0, () => 1)).toBe(1000);
  expect(backoffMs(2, () => 1)).toBe(4000);
  expect(backoffMs(10, () => 1)).toBe(15000);
  expect(backoffMs(3, () => 0)).toBe(4000); // half of 8000
});

test("provisional candles are hollow", () => {
  expect(candleStyle(true, false)).toEqual({});
  expect(candleStyle(false, true)).toMatchObject({ color: "rgba(0,0,0,0)", borderColor: "#ef5350" });
});
