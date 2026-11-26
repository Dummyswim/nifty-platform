import { beforeEach, expect, test } from "vitest";
import { defaultLayout, setLayoutN, updatePane } from "./chart/layout";
import { activePane, indexSymbol, useUi } from "./store";

const focus = { from: 1, to: 2, nonce: 3, tf: "5m" as const, extra: [] };

beforeEach(() => useUi.setState({ page: "backtests", chart: defaultLayout("NIFTY 50", "1m"), focus: null }));

test("openOnChart changes only the active pane and goes to the chart", () => {
  const three = updatePane(setLayoutN(defaultLayout("NIFTY 50", "1m"), 3), 2, { symbol: "OPT", kind: "option", label: "OPT CE" });
  useUi.setState({ chart: { ...three, active: 2 } });
  useUi.getState().openOnChart({ symbol: "SENSEX", tf: "5m", focus });
  const s = useUi.getState();
  expect(s.page).toBe("chart");
  expect(s.focus).toEqual(focus);
  expect(s.chart.panes[2]).toEqual({ symbol: "SENSEX", tf: "5m", kind: "index" });
  expect(s.chart.panes.slice(0, 2).map((p) => [p.symbol, p.tf])).toEqual([["NIFTY 50", "1m"], ["NIFTY 50", "1m"]]);
  expect(activePane(s).symbol).toBe("SENSEX");
});

test("openOnChart without a symbol keeps the pane's instrument and changes the timeframe", () => {
  useUi.getState().openOnChart({ tf: "5m", focus });
  expect(activePane(useUi.getState())).toEqual({ symbol: "NIFTY 50", tf: "5m", kind: "index" });
});

test("indexSymbol skips option panes", () => {
  const two = updatePane(setLayoutN(defaultLayout("NIFTY 50", "1m"), 2), 1, { symbol: "OPT", kind: "option" });
  expect(indexSymbol({ chart: { ...two, active: 1 } })).toBe("NIFTY 50");
  expect(indexSymbol({ chart: updatePane(defaultLayout("X", "1m"), 0, { kind: "option" }) })).toBe("NIFTY 50");
  expect(indexSymbol({ chart: defaultLayout("SENSEX", "1m") })).toBe("SENSEX");
});
