/** JSON Schema (pydantic) -> form fields. `x-ui` properties become the engine's `ui` block. */

export type Schema = {
  properties?: Record<string, Prop>;
  $defs?: Record<string, { properties?: Record<string, Prop> }>;
};
export interface Prop {
  type?: string;
  title?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  enum?: unknown[];
  $ref?: string;
  allOf?: { $ref?: string }[];
  "x-ui"?: boolean;
}

export type FieldKind = "integer" | "number" | "boolean" | "enum" | "json";
export interface Field {
  key: string;
  title: string;
  kind: FieldKind;
  def: unknown;
  min?: number;
  max?: number;
  options?: unknown[];
  ui: boolean;
}

function kindOf(p: Prop): FieldKind {
  if (p.enum) return "enum";
  if (p.type === "integer") return "integer";
  if (p.type === "number") return "number";
  if (p.type === "boolean") return "boolean";
  return "json"; // anything else: raw JSON field
}

function toField(key: string, p: Prop, ui: boolean): Field {
  return {
    key,
    title: p.title ?? key,
    kind: kindOf(p),
    def: p.default,
    min: p.minimum ?? p.exclusiveMinimum,
    max: p.maximum,
    options: p.enum,
    ui,
  };
}

/** Params fields first, then the `ui` block's fields (flagged `ui: true`). */
export function fieldsFromSchema(schema: Schema): Field[] {
  const out: Field[] = [];
  let uiProps: Record<string, Prop> = {};
  for (const [key, p] of Object.entries(schema.properties ?? {})) {
    if (key === "ui") {
      const ref = p.$ref ?? p.allOf?.find((a) => a.$ref)?.$ref;
      uiProps = (ref && schema.$defs?.[ref.split("/").pop()!]?.properties) || {};
      continue;
    }
    out.push(toField(key, p, !!p["x-ui"]));
  }
  for (const [key, p] of Object.entries(uiProps)) out.push(toField(key, p, true));
  return out;
}

export interface Values {
  params: Record<string, unknown>;
  ui: Record<string, unknown>;
}

export function defaultsOf(fields: Field[]): Values {
  const v: Values = { params: {}, ui: {} };
  for (const f of fields) if (f.def !== undefined) (f.ui ? v.ui : v.params)[f.key] = f.def;
  return v;
}

/** Raw input text -> typed value; `undefined` when invalid (the form shows the error). */
export function coerce(f: Field, raw: string | boolean): unknown {
  if (f.kind === "boolean") return Boolean(raw);
  if (f.kind === "enum") return f.options?.find((o) => String(o) === raw);
  if (f.kind === "json") {
    try {
      return JSON.parse(String(raw));
    } catch {
      return undefined;
    }
  }
  const n = Number(raw);
  if (raw === "" || !Number.isFinite(n)) return undefined;
  if (f.kind === "integer" && !Number.isInteger(n)) return undefined;
  if (f.min !== undefined && n < f.min) return undefined;
  if (f.max !== undefined && n > f.max) return undefined;
  return n;
}

/** Only non-default params go to the server (a stable job key); `ui` never does. */
export function paramsForRun(fields: Field[], params: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    if (f.ui) continue;
    const v = params[f.key];
    if (v !== undefined && JSON.stringify(v) !== JSON.stringify(f.def)) out[f.key] = v;
  }
  return out;
}
