import type { PlotsOut } from "../api/schemas";

export function EnginePanel({ id, panel, atEnd }: { id: string; panel: PlotsOut["panel"]; atEnd: boolean }) {
  const rows = ((panel as { rows?: { label: string; value: string; role: string }[] } | null)?.rows ?? []);
  if (rows.length === 0) return null;
  return (
    <div className="panelcard" data-testid="engine-panel">
      <h4>{id}</h4>
      {rows.map((r) => (
        <div key={r.label} className={`prow ${r.role}`}>
          <span>{r.label}</span>
          <b>{String(r.value)}</b>
        </div>
      ))}
      {!atEnd && <p className="muted small">latest bar only (not replayed)</p>}
    </div>
  );
}
