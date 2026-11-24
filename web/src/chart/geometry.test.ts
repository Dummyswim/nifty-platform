import { expect, test } from "vitest";
import {
  type Cols, emptyCols, fmtIst, hitTest, logicalToTime, logicalX, mergeCols, movePoints, tickLabel, timeToLogical,
} from "./geometry";

const T5 = [0, 300, 600, 900, 1200]; // 5m bars
const cols = (ts: number[]): Cols => ({
  t: ts, o: ts.map((x) => x + 1), h: ts.map((x) => x + 2), l: ts.map((x) => x), c: ts.map((x) => x + 1), v: ts.map(() => 0),
});

test("a 1m point keeps its place on a 5m chart (interpolated, not dropped)", () => {
  expect(timeToLogical(T5, 600)).toBe(2);
  expect(timeToLogical(T5, 780)).toBeCloseTo(2.6); // 10:13 between the 10:10 and 10:15 bars
  expect(timeToLogical(T5, 0 + 150)).toBeCloseTo(0.5);
});

test("extrapolates before the first and after the last bar", () => {
  expect(timeToLogical(T5, -300)).toBe(-1);
  expect(timeToLogical(T5, 1500)).toBe(5);
  expect(timeToLogical([], 5)).toBeNull();
});

test("time <-> logical round trip", () => {
  for (const t of [-450, 0, 120, 777, 1200, 1980]) {
    const x = timeToLogical(T5, t)!;
    expect(logicalToTime(T5, x)).toBe(t);
  }
});

test("same instant maps consistently across timeframes", () => {
  const T1 = Array.from({ length: 21 }, (_, i) => i * 60);
  const t = 777;
  const a = logicalToTime(T5, timeToLogical(T5, t)!);
  const b = logicalToTime(T1, timeToLogical(T1, t)!);
  expect(a).toBe(t);
  expect(b).toBe(t);
});

test("hit tests: trendline handles, body, rect, hline, text", () => {
  const tl = { kind: "trendline", a: { x: 0, y: 0 }, b: { x: 100, y: 0 } } as const;
  expect(hitTest(tl, { x: 1, y: 2 })).toBe("p0");
  expect(hitTest(tl, { x: 99, y: -3 })).toBe("p1");
  expect(hitTest(tl, { x: 50, y: 4 })).toBe("body");
  expect(hitTest(tl, { x: 50, y: 30 })).toBeNull();
  expect(hitTest({ kind: "hline", y: 40 }, { x: 5, y: 43 })).toBe("body");
  expect(hitTest({ kind: "hline", y: 40 }, { x: 5, y: 60 })).toBeNull();
  const r = { kind: "rect", a: { x: 10, y: 10 }, b: { x: 60, y: 50 } } as const;
  expect(hitTest(r, { x: 30, y: 30 })).toBe("body");
  expect(hitTest(r, { x: 200, y: 30 })).toBeNull();
  const tx = { kind: "text", a: { x: 20, y: 30 }, w: 40, h: 12 } as const;
  expect(hitTest(tx, { x: 30, y: 25 })).toBe("body");
  expect(hitTest(tx, { x: 30, y: 5 })).toBeNull();
});

test("movePoints moves a handle or the whole drawing", () => {
  const pts = [{ t: 0, p: 100 }, { t: 600, p: 110 }];
  expect(movePoints(T5, pts, "body", 1, -5)).toEqual([{ t: 300, p: 95 }, { t: 900, p: 105 }]);
  expect(movePoints(T5, pts, "p1", 1, 2)).toEqual([{ t: 0, p: 100 }, { t: 900, p: 112 }]);
  expect(movePoints(T5, pts, "p0", -1, 0)[0]).toEqual({ t: -300, p: 100 });
});

test("mergeCols: older page prepends, duplicates dropped, strictly ascending", () => {
  const m = mergeCols(cols([0, 300, 600]), cols([600, 900, 1200]));
  expect(m.t).toEqual([0, 300, 600, 900, 1200]);
  const cur = cols([600, 900]);
  cur.c[0] = 999;
  expect(mergeCols(cols([300, 600]), cur).c[1]).toBe(999); // current wins
  expect(mergeCols(emptyCols(), cols([5])).t).toEqual([5]);
});

test("IST labels", () => {
  const t = Date.UTC(2026, 10, 2, 4, 0) / 1000; // 09:30 IST
  expect(tickLabel(t, 3)).toBe("09:30");
  expect(fmtIst(t)).toContain("09:30");
  expect(tickLabel(t, 2)).toBe("02 Nov");
});

test("logicalX interpolates fractions between whole bars", () => {
  const toX = (i: number) => (i < 0 || i > 100 ? null : 10 + i * 8); // 8 px per bar
  expect(logicalX(3, toX)).toBe(34);
  expect(logicalX(3.5, toX)).toBe(38);
  expect(logicalX(99.005, toX)).toBeCloseTo(802.04); // a time in the overnight gap: just after the last bar, never 0
  expect(logicalX(100.5, toX)).toBe(810); // no right neighbour: the bar itself
  expect(logicalX(-1, toX)).toBeNull();
});
