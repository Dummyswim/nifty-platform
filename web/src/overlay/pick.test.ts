import { expect, test } from "vitest";
import { type El, pickOverlays, roleColor, zoneStyle } from "./pick";

const el = (o: Partial<El>): El => ({
  id: "a", ver: 0, deleted: false, avail: 100, kind: "zone", t0: 50, t1: 200, p0: 1, p1: 2, style: {}, text: null, meta: {}, ...o,
});

test("the latest version available at the cursor wins (supersession)", () => {
  const els = [el({ ver: 0, p0: 1 }), el({ ver: 1, avail: 200, p0: 5 }), el({ ver: 2, avail: 300, p0: 9 })];
  expect(pickOverlays(els, 250, 999).map((e) => e.p0)).toEqual([5]);
  expect(pickOverlays(els, 100, 999).map((e) => e.p0)).toEqual([1]);
  expect(pickOverlays(els, null, 999).map((e) => e.p0)).toEqual([9]);
});

test("future versions and future elements are hidden", () => {
  expect(pickOverlays([el({ avail: 500 })], 300, 999)).toEqual([]);
  expect(pickOverlays([el({ id: "a", avail: 100 }), el({ id: "b", avail: 400 })], 300, 999).map((e) => e.id)).toEqual(["a"]);
});

test("a deleted latest version removes the element, an older live one does not resurface", () => {
  const els = [el({ ver: 0 }), el({ ver: 1, avail: 200, deleted: true })];
  expect(pickOverlays(els, 250, 999)).toEqual([]);
  expect(pickOverlays(els, 150, 999)).toHaveLength(1);
});

test("t1 = null extends to the cursor, or to the last bar without a cursor", () => {
  const open = el({ t0: 50, t1: null });
  expect(pickOverlays([open], 400, 999)[0]!.t1).toBe(400);
  expect(pickOverlays([open], null, 999)[0]!.t1).toBe(999);
  expect(pickOverlays([el({ t1: 200 })], 400, 999)[0]!.t1).toBe(200);
});

test("role tokens map to theme colours, with engine overrides", () => {
  expect(roleColor("demand")).toBe("#26a69a");
  expect(roleColor("supply")).toBe("#ef5350");
  expect(roleColor("nonsense")).toBe(roleColor("neutral"));
  expect(roleColor(undefined)).toBe(roleColor("neutral"));
  expect(roleColor("buy", { buy: "#00ff00" })).toBe("#00ff00");
});

test("zone status styles", () => {
  expect(zoneStyle({ status: "active" })).toEqual({ fillAlpha: 0.18, dashed: false });
  expect(zoneStyle({ status: "mitigated" }).dashed).toBe(true);
  expect(zoneStyle({ status: "projected" })).toEqual({ fillAlpha: 0.1, dashed: true });
  expect(zoneStyle({}).dashed).toBe(false);
});
