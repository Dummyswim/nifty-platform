import type { El } from "../overlay/pick";

type Bag = Record<string, unknown>;
const off = (v: unknown) => v === false;

const NVS_BANDS = new Set(["buy_near", "buy_far", "sell_near", "sell_far"]);
const NVS_LEVELS = new Set(["stop", "target"]);

/** Should this engine plot be drawn? `ui` = the display switches, `params` = engine params. */
export function plotVisible(engineId: string, plot: string, ui: Bag, params: Bag): boolean {
  if (engineId === "pine.nvs_scalper") {
    if (NVS_BANDS.has(plot)) return !off(ui.show_bands);
    if (NVS_LEVELS.has(plot)) return !off(ui.show_levels);
  }
  if (engineId === "pine.balu_zone") {
    if (plot === "golden" || plot === "gold_val") return !off(ui.show_gold);
    if (plot === "moving_line" || plot === "moving_line_raw") return !off(ui.show_cvd);
    if (plot === "or_high" || plot === "or_low") return !off(params.show_key_levels) && !off(params.kl_or);
  }
  return true;
}

/** The overlay to draw, or null when its display switch is off (zone labels lose their text). */
export function overlayFor(engineId: string, el: El, ui: Bag, params: Bag): El | null {
  if (engineId === "pine.nvs_scalper") {
    if (el.id.endsWith(":stop") || el.id.endsWith(":target")) return off(ui.show_levels) ? null : el;
    if (el.id.endsWith(":exit")) return off(ui.show_exit_labels) ? null : el;
    if (el.id.endsWith(":signal") || el.id.endsWith(":entry")) return off(ui.show_labels) ? null : el;
  }
  if (engineId === "pine.balu_zone") {
    if (/^z\d+$/.test(el.id)) {
      if (off(ui.show_zones)) return null;
      return off(ui.show_zone_lbl) ? { ...el, text: null } : el;
    }
    if (el.id.startsWith("kl:")) return off(params.show_key_levels) ? null : el;
  }
  return el;
}
