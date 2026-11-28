import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ContextOut, ContextSide } from "../api/schemas";
import { boxView } from "./pick";
import type { ContextWriting } from "./useMarketContext";

export const WRITING_TITLE: Record<ContextWriting, string> = { iv: "Writing: OI + IV", oi: "Writing: raw OI (reel)" };
const TOGGLE: Record<ContextWriting, { pref: string; label: string }> = {
  iv: { pref: "context.show_iv", label: "OI+IV" },
  oi: { pref: "context.show_oi", label: "raw OI" },
};

const hhmm = (t: number) => new Date((t + 19800) * 1000).toISOString().slice(11, 16); // IST
const signed = (v: number, d: number) => (v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const side = (name: string, s: ContextSide) => `${name} IV ${s.iv!.toFixed(1)}${s.verdict ? ` ${s.verdict}` : ""}`;

export function ContextBox({ writing, data, error, cursor }: { writing: ContextWriting; data?: ContextOut; error?: unknown; cursor: number | null }) {
  const { state: s, note, flags } = boxView(data, cursor, error);
  const na = !s || !!s.na_reason;
  const rows: string[] = [];
  if (s && !note) {
    if (s.vix != null) rows.push(`VIX ${s.vix.toFixed(1)}${s.vix_rank != null ? `  P${Math.round(s.vix_rank)}` : ""}${s.vix_high ? "  HIGH" : ""}`);
    const iv = [s.ce.iv != null && side("CE", s.ce), s.pe.iv != null && side("PE", s.pe)].filter(Boolean);
    if (iv.length) rows.push(iv.join(" · "));
    if (s.straddle_prem != null) rows.push(`Straddle ${Math.round(s.straddle_prem)}${s.fair_straddle_prem != null ? ` / fair ${Math.round(s.fair_straddle_prem)}` : ""}`);
    if (s.w_day != null) {
      const who = s.w_day < 0 ? "CALL" : s.w_day > 0 ? "PUT" : "—";
      rows.push(`Writing ${who} ${signed(s.w_day, 2)}${s.w_roll != null ? ` (15m ${signed(s.w_roll, 2)})` : ""}`);
    }
    if (s.bias === "BEARISH" || s.bias === "BULLISH") {
      const since = s.bias_since != null ? `  since ${hhmm(s.bias_since)}` : "";
      rows.push(s.bias === "BEARISH" ? `▼ BEARISH · buy PE ok${since}` : `▲ BULLISH · buy CE ok${since}`);
    } else rows.push("NO BIAS");
    if (s.day_move_pts != null && s.exp_move_pts != null)
      rows.push(`Move ${signed(Math.round(s.day_move_pts), 0)} / ±${Math.round(s.exp_move_pts)} · ${Math.round((Math.abs(s.day_move_pts) / s.exp_move_pts) * 100)} %`);
  }
  return (
    <div className="context-box" data-testid={`context-box-${writing}`} data-bias={s?.bias ?? "NONE"} data-na={na ? "1" : undefined}>
      <div className="ctx-head">{WRITING_TITLE[writing]}{s && ` ${hhmm(s.t)}`}</div>
      {note ? <div className="ctx-na">{note}</div> : rows.map((r) => <div key={r}>{r}</div>)}
      {flags.length > 0 && <div className="ctx-flags">{flags.join(" · ")}</div>}
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
