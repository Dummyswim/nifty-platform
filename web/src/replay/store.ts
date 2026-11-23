import { create } from "zustand";
import type { Speed } from "./logic";

interface Replay {
  cursor: number | null; // UTC epoch seconds; null = end of data
  playing: boolean;
  speed: Speed;
  set: (p: Partial<Omit<Replay, "set">>) => void;
  exit: () => void;
}

export const useReplay = create<Replay>((set) => ({
  cursor: null,
  playing: false,
  speed: 5,
  set: (p) => set(p),
  exit: () => set({ cursor: null, playing: false }),
}));
