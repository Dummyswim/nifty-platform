import { describe, expect, it } from "vitest";
import type { EngineOut } from "../api/schemas";
import { engineTf } from "./useIndicators";

const eng = (id: string, tf = "5m") => ({ id, default_timeframe: tf }) as EngineOut;

describe("engine timeframe in the history view", () => {
  it("Pine ports follow a 5m/15m/30m chart, otherwise their default", () => {
    expect(engineTf(eng("pine.balu_zone"), "15m")).toBe("15m");
    expect(engineTf(eng("pine.nvs_scalper"), "30m")).toBe("30m");
    expect(engineTf(eng("pine.balu_zone"), "1m")).toBe("5m");
    expect(engineTf(eng("pine.balu_zone"), "1D")).toBe("5m");
  });
  it("the research engine always uses its own timeframe", () => {
    expect(engineTf(eng("research.distance_entry_v1", "1m"), "15m")).toBe("1m");
  });
});
