import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { ContextOut } from "../api/schemas";
import { collapsedLine, hhmm, moveLine, ruleLine, RULE_LABEL, vixLine, wallsLine } from "./format";
import { boxView } from "./pick";
import type { ContextWriting } from "./useMarketContext";

const TOGGLE: Record<ContextWriting, { pref: string; label: string }> = {
  iv: { pref: "context.show_iv", label: "OI+IV" },
  oi: { pref: "context.show_oi", label: "raw OI" },
};

export interface ContextRule { writing: ContextWriting; data?: ContextOut; error?: unknown }

// collapse is a per-viewer convenience: storage may be missing or throw (private mode, blocked site data)
const storeKey = (pane: number) => `ctx-collapsed:${pane}`;
function readCollapsed(pane: number): boolean {
  try { return localStorage.getItem(storeKey(pane)) === "1"; } catch { return false; }
}
function writeCollapsed(pane: number, on: boolean) {
  try { if (on) localStorage.setItem(storeKey(pane), "1"); else localStorage.removeItem(storeKey(pane)); } catch { /* convenience only */ }
}

/** One box for the enabled writing rules: shared lines from the iv state if present, else oi; one line per rule. */
export function ContextBox({ paneIndex, rules, cursor }: { paneIndex: number; rules: ContextRule[]; cursor: number | null }) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(paneIndex));
  const views = rules.map((r) => ({ writing: r.writing, ...boxView(r.data, cursor, r.error) }));
  const shared = views.find((v) => v.state) ?? views[0];
  const s = shared?.state ?? null;
  const na = !s || !!s.na_reason;
  const flags = [...new Set(views.flatMap((v) => v.flags))];
  const rows: string[] = [];
  if (s && !shared.note) {
    const v = vixLine(s);
    if (v) rows.push(v);
  }
  if (s) {
    const m = moveLine(s);
    if (m) rows.push(m);
    const w = wallsLine(s.call_wall, s.put_wall);
    if (w) rows.push(w);
  }
  const toggle = () => { setCollapsed(!collapsed); writeCollapsed(paneIndex, !collapsed); };
  const bias = (v: (typeof views)[number]) => v.state?.bias ?? "NONE";
  const attrs = Object.fromEntries(views.map((v) => [`data-bias-${v.writing}`, bias(v)]));
  return (
    <div className="context-box" data-testid="context-box" data-na={na ? "1" : undefined} data-collapsed={collapsed ? "1" : undefined} {...attrs}>
      <div className="ctx-head" data-testid="ctx-head" role="button" tabIndex={0} title={collapsed ? "Expand" : "Collapse"} onClick={toggle}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } }}>
        {collapsed
          ? collapsedLine(views.map((v) => [v.writing, bias(v)]), s?.room_left_pts, s?.late)
          : `Market context${s ? ` ${hhmm(s.t)}` : ""}`}
      </div>
      {!collapsed && (
        <>
          {shared?.note && <div className="ctx-na">{shared.note}</div>}
          {rows.map((r) => <div key={r}>{r}</div>)}
          {views.map((v) => (
            <div key={v.writing} className="ctx-rule" data-testid={`ctx-rule-${v.writing}`} data-bias={bias(v)}>
              {v.state && !v.note ? ruleLine(v.writing, v.state) : `${RULE_LABEL[v.writing]} ${v.note === shared.note ? "n/a" : v.note}`}
            </div>
          ))}
          {flags.length > 0 && <div className="ctx-flags">{flags.join(" · ")}</div>}
        </>
      )}
    </div>
  );
}

/** Sidebar switch for pref `context.show_iv` / `context.show_oi` (default on). */
export function ContextToggle({ writing }: { writing: ContextWriting }) {
  const { pref, label } = TOGGLE[writing];
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  const save = useMutation({
    mutationFn: (value: boolean) => api(`/prefs/${pref}`, { method: "PUT", body: { value } }),
    // cancel an in-flight prefs refetch so it cannot overwrite the optimistic value
    onMutate: async (value) => {
      await qc.cancelQueries({ queryKey: ["prefs"] });
      const prev = qc.getQueryData<Record<string, unknown>>(["prefs"]);
      qc.setQueryData(["prefs"], (old: Record<string, unknown> | undefined) => ({ ...(old ?? {}), [pref]: value }));
      return { prev };
    },
    onError: (_e, _v, ctx) => qc.setQueryData(["prefs"], ctx?.prev),
    onSettled: () => qc.invalidateQueries({ queryKey: ["prefs"] }),
  });
  return (
    <label className="ctx-toggle">
      <input type="checkbox" role="switch" checked={prefs.data?.[pref] !== false} onChange={(e) => save.mutate(e.target.checked)} aria-label={`Toggle market context ${label}`} />
      <span>Market context: {label}</span>
    </label>
  );
}
