import { expect, test } from "vitest";
import { coerce, defaultsOf, fieldsFromSchema, paramsForRun, type Schema } from "./schemaForm";

const schema: Schema = {
  properties: {
    ema_fast_len: { type: "integer", title: "Ema Fast Len", default: 9, minimum: 1 },
    close_pos_min: { type: "number", default: 0.6, minimum: 0.5, maximum: 1 },
    use_rsi: { type: "boolean", default: true },
    anchor_mode: { enum: ["signal_close", "fill_price"], default: "signal_close", type: "string" },
    weird: { type: "array" },
    ui: { $ref: "#/$defs/NvsUi", "x-ui": true },
  },
  $defs: { NvsUi: { properties: { show_bands: { type: "boolean", default: true, "x-ui": true }, color_vwap: { type: "string", default: "#f59e0b", "x-ui": true } } } },
};

test("fields: number/int with bounds, bool, enum, raw JSON; ui block flagged", () => {
  const f = fieldsFromSchema(schema);
  const by = Object.fromEntries(f.map((x) => [x.key, x]));
  expect(by.ema_fast_len).toMatchObject({ kind: "integer", min: 1, ui: false, def: 9 });
  expect(by.close_pos_min).toMatchObject({ kind: "number", min: 0.5, max: 1 });
  expect(by.use_rsi!.kind).toBe("boolean");
  expect(by.anchor_mode).toMatchObject({ kind: "enum", options: ["signal_close", "fill_price"] });
  expect(by.weird!.kind).toBe("json");
  expect(by.show_bands).toMatchObject({ kind: "boolean", ui: true });
  expect(by.ui).toBeUndefined();
});

test("defaults split into params and ui", () => {
  const d = defaultsOf(fieldsFromSchema(schema));
  expect(d.params).toMatchObject({ ema_fast_len: 9, use_rsi: true });
  expect(d.ui).toEqual({ show_bands: true, color_vwap: "#f59e0b" });
});

test("coerce validates bounds, integers, enums and JSON", () => {
  const f = Object.fromEntries(fieldsFromSchema(schema).map((x) => [x.key, x]));
  expect(coerce(f.ema_fast_len!, "12")).toBe(12);
  expect(coerce(f.ema_fast_len!, "0")).toBeUndefined();
  expect(coerce(f.ema_fast_len!, "1.5")).toBeUndefined();
  expect(coerce(f.close_pos_min!, "1.2")).toBeUndefined();
  expect(coerce(f.anchor_mode!, "fill_price")).toBe("fill_price");
  expect(coerce(f.anchor_mode!, "nope")).toBeUndefined();
  expect(coerce(f.weird!, "[1,2]")).toEqual([1, 2]);
  expect(coerce(f.weird!, "[1,")).toBeUndefined();
  expect(coerce(f.use_rsi!, false)).toBe(false);
});

test("run params exclude defaults and ui (stable job key; ui-only edits never rerun)", () => {
  const f = fieldsFromSchema(schema);
  expect(paramsForRun(f, { ema_fast_len: 9, use_rsi: false, show_bands: false })).toEqual({ use_rsi: false });
  expect(paramsForRun(f, {})).toEqual({});
});
