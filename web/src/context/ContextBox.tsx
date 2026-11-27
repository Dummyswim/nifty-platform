import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ContextOut, ContextSide } from "../api/schemas";
import { pickState } from "./pick";

const hhmm = (t: number) => new Date((t + 19800) * 1000).toISOString().slice(11, 16); // IST
const signed = (v: number, d: number) => (v < 0 ? "−" : "") + Math.abs(v).toFixed(d);
const side = (name: string, s: ContextSide) => `${name} IV ${s.iv!.toFixed(1)}${s.verdict ? ` ${s.verdict}` : ""}`;

export function ContextBox({ data, cursor }: { data?: ContextOut; cursor: number | null }) {
  const s = data ? pickState(data.series, cursor) : null;
  const na = !s || !!s.na_reason;
  const rows: string[] = [];
  let note: string | null = null;
  if (!s) {
    note = data?.notes[0] ?? "no data";
  } else if (s.na_reason) {
    note = s.na_reason.includes("n/a") ? s.na_reason : `n/a: ${s.na_reason}`;
  } else {
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
    <div className="context-box" data-testid="context-box" data-bias={s?.bias ?? "NONE"} data-na={na ? "1" : undefined}>
      <div className="ctx-head">Market context{s && ` ${hhmm(s.t)}`}</div>
      {note ? <div className="ctx-na">{note}</div> : rows.map((r) => <div key={r}>{r}</div>)}
    </div>
  );
}

/** Sidebar switch for pref `context.show` (default on). */
export function ContextToggle() {
  const qc = useQueryClient();
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  const save = useMutation({
    mutationFn: (value: boolean) => api("/prefs/context.show", { method: "PUT", body: { value } }),
    // cancel an in-flight prefs refetch so it cannot overwrite the optimistic value
    onMutate: async (value) => {
      await qc.cancelQueries({ queryKey: ["prefs"] });
      qc.setQueryData(["prefs"], (old: Record<string, unknown> | undefined) => ({ ...(old ?? {}), "context.show": value }));
    },
  });
  return (
    <label className="ctx-toggle">
      <input type="checkbox" role="switch" checked={prefs.data?.["context.show"] !== false} onChange={(e) => save.mutate(e.target.checked)} aria-label="Toggle market context" />
      <span>Market context</span>
    </label>
  );
}
