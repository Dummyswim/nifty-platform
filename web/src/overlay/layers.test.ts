import { expect, test } from "vitest";
import { type PlotLayer, plotLayers, revealPlot, splitRuns } from "./layers";

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
