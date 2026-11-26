import { create } from "zustand";
import type { Tf } from "./chart/geometry";
import { type ChartLayout, type PaneState, defaultLayout, updatePane } from "./chart/layout";
import type { El } from "./overlay/pick";

export type Page = "chart" | "backtests" | "research" | "analytics" | "options" | "settings";

/** Set by the audit drawer: the chart scrolls to the trade and draws its levels. */
export interface Focus {
  from: number;
  to: number;
  nonce: number;
  tf: Tf;
  extra: El[];
  /** the pane it was opened in (set by openOnChart); other panes ignore it */
  pane?: number;
}

interface Ui {
  page: Page;
  /** chart panes; the toolbar acts on `chart.active` */
  chart: ChartLayout;
  restored: boolean;
  focus: Focus | null;
  backtestId: string | null;
  set: (p: Partial<Omit<Ui, "set" | "setChart" | "openOnChart">>) => void;
  setChart: (l: ChartLayout) => void;
  /** Backtests/Research "Open on chart": the active pane shows the symbol/tf and scrolls to `focus` */
  openOnChart: (o: { symbol?: string; tf: Tf; focus: Omit<Focus, "pane"> }) => void;
}

export const activePane = (s: Pick<Ui, "chart">): PaneState => s.chart.panes[s.chart.active] ?? s.chart.panes[0]!;

/** Default instrument for new backtests/research runs: an index pane, never an option contract. */
export const indexSymbol = (s: Pick<Ui, "chart">): string => {
  const a = activePane(s);
  if (a.kind === "index") return a.symbol;
  return s.chart.panes.find((p) => p.kind === "index")?.symbol ?? "NIFTY 50";
};

export const useUi = create<Ui>((set) => ({
  page: "chart",
  chart: defaultLayout("NIFTY 50", "1m"),
  restored: false,
  focus: null,
  backtestId: null,
  set: (p) => set(p),
  setChart: (chart) => set({ chart }),
  openOnChart: ({ symbol, tf, focus }) =>
    set((s) => {
      // backtest/research markers are index trades: never draw them on an option contract
      const sym = symbol ?? (activePane(s).kind === "option" ? indexSymbol(s) : undefined);
      const patch: Partial<PaneState> = sym ? { symbol: sym, tf, kind: "index" } : { tf };
      const chart = updatePane(s.chart, s.chart.active, patch);
      if (sym) delete chart.panes[s.chart.active]!.label;
      return { page: "chart", focus: { ...focus, pane: s.chart.active }, chart };
    }),
}));
