import { expect, test } from "vitest";
import { clampFrac, defaultLayout, dragFrac, fromPrefs, setLayoutN, toPrefs, updatePane } from "./layout";

const fb = { symbol: "NIFTY 50", tf: "1m" as const };

test("default layout is one pane on the given symbol with equal sizes", () => {
  expect(defaultLayout("NIFTY 50", "5m")).toEqual({
    layout: 1, active: 0, panes: [{ symbol: "NIFTY 50", tf: "5m", kind: "index" }], sizes: { col: 0.5, row: 0.5 },
  });
});

test("growing copies the active pane, shrinking keeps the first panes and clamps active", () => {
  const one = updatePane(defaultLayout("NIFTY 50", "1m"), 0, { tf: "5m" });
  const three = setLayoutN(one, 3);
  expect(three.panes).toHaveLength(3);
  expect(three.panes.every((p) => p.symbol === "NIFTY 50" && p.tf === "5m")).toBe(true);
  const c = updatePane({ ...three, active: 2 }, 1, { symbol: "B" });
  const two = setLayoutN(c, 2);
  expect(two.panes.map((p) => p.symbol)).toEqual(["NIFTY 50", "B"]);
  expect(two.active).toBe(1);
  expect(setLayoutN(two, 1).panes).toHaveLength(1);
});

test("divider maths clamps to 15 %..85 %", () => {
  expect(dragFrac(0.5, 100, 1000)).toBeCloseTo(0.6);
  expect(dragFrac(0.5, -900, 1000)).toBe(0.15);
  expect(dragFrac(0.5, 900, 1000)).toBe(0.85);
  expect(dragFrac(0.5, 10, 0)).toBe(0.5); // not laid out yet
  expect(clampFrac(Number.NaN)).toBe(0.5);
});

test("prefs: old chart pref seeds a one-pane layout", () => {
  expect(fromPrefs(undefined, { symbol: "X", tf: "5m" }, fb)).toEqual(defaultLayout("X", "5m"));
  expect(fromPrefs(undefined, undefined, fb)).toEqual(defaultLayout("NIFTY 50", "1m"));
});

test("prefs: malformed or partial layouts fall back to sane values", () => {
  const l = fromPrefs({ layout: 3, active: 7, panes: [{ symbol: "A", tf: "2m", kind: "option", label: "A CE" }] }, undefined, fb);
  expect(l.layout).toBe(3);
  expect(l.panes).toHaveLength(3);
  expect(l.panes[0]).toEqual({ symbol: "A", tf: "1m", kind: "option", label: "A CE" }); // unknown tf -> fallback tf
  expect(l.panes[2]).toEqual({ symbol: "A", tf: "1m", kind: "option", label: "A CE" }); // padded from pane A
  expect(l.active).toBe(0);
  expect(l.sizes).toEqual({ col: 0.5, row: 0.5 });
  expect(fromPrefs({ layout: 9, panes: "x", sizes: { col: 2 } }, undefined, fb)).toEqual({ ...defaultLayout("NIFTY 50", "1m"), sizes: { col: 0.85, row: 0.5 } });
  expect(fromPrefs("junk", null, fb)).toEqual(defaultLayout("NIFTY 50", "1m"));
});

test("toPrefs writes the layout and the old chart pref from pane A", () => {
  const l = setLayoutN(updatePane(defaultLayout("NIFTY 50", "3m"), 0, {}), 2);
  const p = toPrefs(updatePane(l, 1, { symbol: "OPT", kind: "option" }));
  expect(p.chart).toEqual({ symbol: "NIFTY 50", tf: "3m" });
  expect(p.chart_layout.panes[1]!.symbol).toBe("OPT");
  expect(fromPrefs(p.chart_layout, p.chart, fb)).toEqual(p.chart_layout); // round trip
});
