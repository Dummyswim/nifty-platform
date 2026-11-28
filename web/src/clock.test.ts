import { describe, expect, it } from "vitest";
import { istClock } from "./clock";

describe("istClock", () => {
  it("formats a UTC instant as IST date and time", () => {
    // 2026-11-27 04:02:15 UTC = 09:32:15 IST
    expect(istClock(new Date(Date.UTC(2026, 10, 27, 4, 2, 15)))).toBe("Fri 27 Nov 2026 · 09:32:15 IST");
  });

  it("rolls the date over at IST midnight, not UTC midnight", () => {
    // 2026-11-27 18:30:00 UTC = 28 Nov 00:00:00 IST
    expect(istClock(new Date(Date.UTC(2026, 10, 27, 18, 30, 0)))).toBe("Sat 28 Nov 2026 · 00:00:00 IST");
  });
});
