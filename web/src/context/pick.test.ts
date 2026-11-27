import { describe, expect, it } from "vitest";
import type { ContextState } from "../api/schemas";
import { pickState } from "./pick";

const st = (t: number) => ({ t, bias: "NONE", candidate: "NONE", ce: {}, pe: {} }) as ContextState;
const series = [st(100), st(160), st(220)];

describe("pickState", () => {
  it("null cursor -> last state", () => expect(pickState(series, null)?.t).toBe(220));
  it("cursor between two states -> the earlier one", () => expect(pickState(series, 200)?.t).toBe(160));
  it("cursor exactly on a state -> that state", () => expect(pickState(series, 160)?.t).toBe(160));
  it("cursor before the first state -> null", () => expect(pickState(series, 99)).toBeNull());
  it("empty series -> null", () => {
    expect(pickState([], null)).toBeNull();
    expect(pickState([], 100)).toBeNull();
  });
});
