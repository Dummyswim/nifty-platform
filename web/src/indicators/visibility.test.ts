import { describe, expect, it } from "vitest";
import type { El } from "../overlay/pick";
import { overlayFor, plotVisible } from "./visibility";

const el = (id: string): El => ({ id, ver: 0, deleted: false, avail: 0, kind: "zone", t0: 0, t1: null, p0: 1, p1: 0, style: {}, text: "Supply", meta: {} });

describe("indicator display switches", () => {
  it("hides Balu gold and moving lines, keeps others", () => {
    expect(plotVisible("pine.balu_zone", "golden", { show_gold: false }, {})).toBe(false);
    expect(plotVisible("pine.balu_zone", "moving_line", { show_cvd: false }, {})).toBe(false);
    expect(plotVisible("pine.balu_zone", "moving_line", {}, {})).toBe(true);
    expect(plotVisible("pine.balu_zone", "or_high", {}, { show_key_levels: false })).toBe(false);
    expect(plotVisible("pine.balu_zone", "or_high", {}, { kl_or: false })).toBe(false);
  });
  it("hides NVS bands and levels", () => {
    expect(plotVisible("pine.nvs_scalper", "buy_near", { show_bands: false }, {})).toBe(false);
    expect(plotVisible("pine.nvs_scalper", "stop", { show_levels: false }, {})).toBe(false);
    expect(plotVisible("pine.nvs_scalper", "vwap", { show_bands: false }, {})).toBe(true);
  });
  it("zones: off hides them, labels off strips the text, key levels follow the param", () => {
    expect(overlayFor("pine.balu_zone", el("z5"), { show_zones: false }, {})).toBeNull();
    expect(overlayFor("pine.balu_zone", el("z5"), { show_zone_lbl: false }, {})?.text).toBeNull();
    expect(overlayFor("pine.balu_zone", el("z5"), {}, {})?.text).toBe("Supply");
    expect(overlayFor("pine.balu_zone", el("kl:PDH:2026-11-16"), {}, { show_key_levels: false })).toBeNull();
  });
  it("NVS labels and levels", () => {
    expect(overlayFor("pine.nvs_scalper", el("nvs:t:exit"), { show_exit_labels: false }, {})).toBeNull();
    expect(overlayFor("pine.nvs_scalper", el("nvs:t:signal"), { show_labels: false }, {})).toBeNull();
    expect(overlayFor("pine.nvs_scalper", el("nvs:t:stop"), { show_levels: false }, {})).toBeNull();
    expect(overlayFor("pine.nvs_scalper", el("nvs:t:stop"), {}, {})).not.toBeNull();
  });
});
