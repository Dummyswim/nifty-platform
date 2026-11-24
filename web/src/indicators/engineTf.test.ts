import { describe, expect, it } from "vitest";
import type { EngineOut } from "../api/schemas";
import { engineTf } from "./useIndicators";

const eng = (id: string, tf = "5m") => ({ id, default_timeframe: tf }) as EngineOut;

describe("engine timeframe in the history view", () => {
  it("Pine ports follow an intraday chart, otherwise (1D) their default", () => {
    expect(engineTf(eng("pine.balu_zone"), "15m")).toBe("15m");
    expect(engineTf(eng("pine.nvs_scalper"), "30m")).toBe("30m");
    expect(engineTf(eng("pine.balu_zone"), "1m")).toBe("1m");
    expect(engineTf(eng("pine.nvs_scalper"), "1h")).toBe("1h");
    expect(engineTf(eng("pine.balu_zone"), "1D")).toBe("5m"); // no daily bars in the runner
  });
  it("the research engine always uses its own timeframe", () => {
    expect(engineTf(eng("research.distance_entry_v1", "1m"), "15m")).toBe("1m");
  });
});
