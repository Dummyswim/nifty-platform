import { create } from "zustand";
import type { Tf } from "./chart/geometry";

export type Page = "chart" | "settings";

interface Ui {
  page: Page;
  symbol: string;
  tf: Tf;
  restored: boolean;
  set: (p: Partial<Omit<Ui, "set">>) => void;
}

export const useUi = create<Ui>((set) => ({
  page: "chart",
  symbol: "NIFTY 50",
  tf: "1m",
  restored: false,
  set: (p) => set(p),
}));
