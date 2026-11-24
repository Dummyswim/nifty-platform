import { describe, expect, it, test } from "vitest";
import { type PlotLayer, bandFills, plotLayers, revealPlot, splitRuns } from "./layers";

const layer: PlotLayer = { key: "e:x", name: "x", kind: "step", color: "#fff", pane: "overlay", t: [0, 300, 600, 900, 1200], v: [null, 5, 6, null, 7], barSec: 300 };

test("plot points are known once their bar closed; nulls are gaps", () => {
  expect(revealPlot(layer, null)).toHaveLength(5);
  expect(revealPlot(layer, 600).map((p) => p.time)).toEqual([0, 300]); // bar 600 closes at 900
  expect(revealPlot(layer, 900).find((p) => p.time === 600)).toEqual({ time: 600, value: 6 });
});

test("step plots split into one run per trade", () => {
  expect(splitRuns(revealPlot(layer, null))).toEqual([
    [{ time: 300, value: 5 }, { time: 600, value: 6 }],
    [{ time: 1200, value: 7 }],
  ]);
  expect(splitRuns([])).toEqual([]);
});

test("hidden plots are not drawn", () => {
  const engine = { id: "e", plots: [{ name: "a", kind: "line", role: "neutral", pane: "overlay" }, { name: "b", kind: "line", role: "hidden", pane: "own" }] } as unknown as Parameters<typeof plotLayers>[0];
  const plots = { run_id: "r", timeframe: "5m", t: [0], series: { a: [1], b: [2] }, panel: null } as unknown as Parameters<typeof plotLayers>[1];
  expect(plotLayers(engine, plots, 300, {}).map((l) => l.name)).toEqual(["a"]);
});

describe("bandFills", () => {
  const layer = (name: string, v: (number | null)[]): PlotLayer => ({ key: `e:${name}`, name, kind: "line", color: "#1b9e4b33", pane: "overlay", t: [60, 120, 180, 240], v, barSec: 60 });
  it("pairs near/far edges into shaded runs, split on gaps and kept to candle times", () => {
    const f = bandFills([layer("buy_near", [1, 2, null, 4]), layer("buy_far", [3, 5, 6, 7])], null, new Set([60, 120, 180, 240]));
    expect(f).toHaveLength(1);
    expect(f[0]!.color).toBe("#1b9e4b14");
    expect(f[0]!.pts).toEqual([[{ time: 60, hi: 3, lo: 1 }, { time: 120, hi: 5, lo: 2 }], [{ time: 240, hi: 7, lo: 4 }]]);
    expect(bandFills([layer("buy_near", [1, 2, 3, 4])], null, new Set([60]))).toEqual([]); // far edge hidden => no fill
    expect(bandFills([layer("buy_near", [1, 2, 3, 4]), layer("buy_far", [3, 5, 6, 7])], null, new Set([120]))[0]!.pts).toEqual([[{ time: 120, hi: 5, lo: 2 }]]);
  });
});
