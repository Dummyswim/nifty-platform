import { useState } from "react";
import type { EngineOut } from "../api/schemas";
import { type Field, coerce } from "./schemaForm";
import { type IndState, type RunStatus, fieldsOf } from "./useIndicators";

export function FieldInput({ f, value, onChange }: { f: Field; value: unknown; onChange: (v: unknown) => void }) {
  const [raw, setRaw] = useState<string | null>(null);
  const bad = raw !== null && coerce(f, raw) === undefined;
  if (f.kind === "boolean")
    return <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} aria-label={f.title} />;
  if (f.kind === "enum")
    return (
      <select value={String(value)} onChange={(e) => onChange(coerce(f, e.target.value))} aria-label={f.title}>
        {f.options?.map((o) => <option key={String(o)}>{String(o)}</option>)}
      </select>
    );
  const shown = raw ?? (f.kind === "json" || typeof value === "string" ? (typeof value === "string" ? value : JSON.stringify(value)) : String(value ?? ""));
  return (
    <input
      className={bad ? "bad" : ""}
      value={shown}
      aria-label={f.title}
      aria-invalid={bad}
      type={f.kind === "json" || typeof value === "string" ? "text" : "number"}
      step={f.kind === "integer" ? 1 : "any"}
      min={f.min}
      max={f.max}
      onChange={(e) => {
        setRaw(e.target.value);
        const v = typeof value === "string" ? e.target.value : coerce(f, e.target.value);
        if (v !== undefined) onChange(v);
      }}
      onBlur={() => setRaw(null)}
    />
  );
}

export function IndicatorPanel(props: {
  engines: EngineOut[];
  state: Record<string, IndState>;
  status: Record<string, RunStatus>;
  update: (id: string, patch: Partial<IndState>) => void;
}) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <aside className="indicators" aria-label="Indicators">
      <h3>Indicators</h3>
      {props.engines.map((e) => {
        const st = props.state[e.id]!;
        const rs = props.status[e.id];
        const fields = fieldsOf(e);
        return (
          <div key={e.id} className="ind" data-engine={e.id}>
            <label className="row">
              <input type="checkbox" role="switch" checked={st.enabled} onChange={(ev) => props.update(e.id, { enabled: ev.target.checked })} aria-label={`Toggle ${e.id}`} />
              <span className="name">{e.id}</span>
              <button className="ghost" onClick={() => setOpen(open === e.id ? null : e.id)} aria-expanded={open === e.id}>⚙</button>
            </label>
            {st.enabled && rs && (
              <p className={`chip ${rs.state}`} role="status" data-testid={`status-${e.id}`}>
                {rs.state === "running" ? "running…" : rs.state === "failed" ? `failed: ${rs.error}` : "ready"}
              </p>
            )}
            {open === e.id && (
              <div className="form">
                {fields.map((f) => (
                  <label key={f.key} className="f">
                    <span title={f.key}>{f.ui ? "🎨 " : ""}{f.title}</span>
                    <FieldInput
                      f={f}
                      value={(f.ui ? st.ui : st.params)[f.key] ?? f.def}
                      onChange={(v) => props.update(e.id, f.ui ? { ui: { ...st.ui, [f.key]: v } } : { params: { ...st.params, [f.key]: v } })}
                    />
                  </label>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </aside>
  );
}
