import { create } from "zustand";
import type { Tf } from "./chart/geometry";
import type { El } from "./overlay/pick";

export type Page = "chart" | "backtests" | "analytics" | "options" | "settings";

/** Set by the audit drawer: the chart scrolls to the trade and draws its levels. */
export interface Focus {
  from: number;
  to: number;
  nonce: number;
  tf: Tf;
  extra: El[];
}

interface Ui {
  page: Page;
  symbol: string;
  tf: Tf;
  restored: boolean;
  focus: Focus | null;
  backtestId: string | null;
  set: (p: Partial<Omit<Ui, "set">>) => void;
}

export const useUi = create<Ui>((set) => ({
  page: "chart",
  symbol: "NIFTY 50",
  tf: "1m",
  restored: false,
  focus: null,
  backtestId: null,
  set: (p) => set(p),
}));
