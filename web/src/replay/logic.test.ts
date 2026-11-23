import { expect, test } from "vitest";
import { availableBy, istToEpoch, jumpCursor, stepCursor, tickMs, visibleCount } from "./logic";

const T = [0, 60, 120, 180, 240]; // 1m bars; bar i ends at 60*(i+1)

test("bars are revealed once finished", () => {
  expect(visibleCount(T, "1m", null)).toBe(5);
  expect(visibleCount(T, "1m", 59)).toBe(0);
  expect(visibleCount(T, "1m", 60)).toBe(1);
  expect(visibleCount(T, "1m", 150)).toBe(2);
  expect(visibleCount(T, "1m", 10_000)).toBe(5);
});

test("stepping reveals one bar at a time and ends with null", () => {
  let c: number | null = 60; // 1 bar shown
  const shown: number[] = [];
  for (let i = 0; i < 6 && c !== null; i++) {
    c = stepCursor(T, "1m", c, 1);
    shown.push(visibleCount(T, "1m", c));
  }
  expect(shown).toEqual([2, 3, 4, 5]);
  expect(c).toBeNull();
});

test("stepping back from the end and at the start", () => {
  const c = stepCursor(T, "1m", null, -1);
  expect(visibleCount(T, "1m", c)).toBe(4);
  expect(visibleCount(T, "1m", stepCursor(T, "1m", 60, -1))).toBe(1); // never below one bar
});

test("jump shows the bar containing t", () => {
  expect(visibleCount(T, "1m", jumpCursor(T, "1m", 130))).toBe(3);
  expect(jumpCursor(T, "1m", 10_000)).toBeNull();
});

test("availability filter and speeds", () => {
  const ev = [{ a: 100 }, { a: 200 }, { a: 300 }];
  expect(availableBy(ev, (e) => e.a, 200).map((e) => e.a)).toEqual([100, 200]);
  expect(availableBy(ev, (e) => e.a, null)).toHaveLength(3);
  expect([1, 5, 20, 100].map((s) => tickMs(s as 1))).toEqual([1000, 200, 50, 10]);
});

test("IST input -> epoch", () => {
  expect(istToEpoch("2026-11-02T09:30")).toBe(Date.UTC(2026, 10, 2, 4, 0) / 1000);
});
