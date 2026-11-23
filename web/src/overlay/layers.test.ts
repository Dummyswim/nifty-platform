import { expect, test } from "vitest";
import { type PlotLayer, revealPlot, splitRuns } from "./layers";

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
