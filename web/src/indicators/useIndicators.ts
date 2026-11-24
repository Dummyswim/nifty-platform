import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../api/client";
import type { EngineOut, EventsOut, JobOut, OverlaysOut, PlotsOut, SubmitOut } from "../api/schemas";
import { TF_SEC } from "../replay/logic";
import type { Tf } from "../chart/geometry";
import { type PlotLayer, plotLayers } from "../overlay/layers";
import { overlayFor, plotVisible } from "./visibility";
import { type El, toEl } from "../overlay/pick";
import { type Field, type Schema, defaultsOf, fieldsFromSchema, paramsForRun } from "./schemaForm";

export interface IndState {
  enabled: boolean;
  params: Record<string, unknown>;
  ui: Record<string, unknown>;
}
export type IndPrefs = Record<string, IndState>;
export const DEFAULT_ENABLED = "pine.nvs_scalper"; // success criterion: VWAP strategy overlays automatically

export type RunStatus = { state: "running" } | { state: "failed"; error: string } | { state: "ready"; runId: string };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Submit `engines/{id}/run` (same key => cached run), poll the job, resolve to the run id. */
/** History view: a Pine port runs on the chart's own timeframe (as in TradingView) when that is 5m, 15m or 30m;
 *  otherwise (and for the research engine, and live) on its default timeframe. */
export function engineTf(engine: EngineOut, chartTf: string): string {
  return engine.id.startsWith("pine.") && ["5m", "15m", "30m"].includes(chartTf) ? chartTf : engine.default_timeframe;
}

export async function runEngine(engine: EngineOut, symbol: string, params: Record<string, unknown>, timeframe: string = engine.default_timeframe): Promise<string> {
  const sub = await api<SubmitOut>(`/engines/${engine.id}/run`, { body: { symbol, timeframe, params } });
  for (let i = 0; i < 240; i++) {
    const j = await api<JobOut>(`/jobs/${sub.job_id}`);
    if (j.status === "done" && j.result_ref) return j.result_ref;
    if (j.status === "failed") throw new Error(j.error ?? "engine run failed");
    await sleep(i < 4 ? 250 : 750);
  }
  throw new Error("engine run timed out");
}

export function fieldsOf(engine: EngineOut): Field[] {
  return fieldsFromSchema(engine.params_schema as Schema);
}

export function useIndicators(symbol: string, chartTf: string, live: { source: string; version: number } | null = null) {
  const qc = useQueryClient();
  const engines = useQuery({ queryKey: ["engines"], queryFn: () => api<EngineOut[]>("/engines") });
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });

  const state = useMemo((): IndPrefs => {
    const saved = (prefs.data?.["indicators"] ?? {}) as IndPrefs;
    const out: IndPrefs = {};
    for (const e of engines.data ?? []) {
      const d = defaultsOf(fieldsOf(e));
      const s = saved[e.id];
      out[e.id] = {
        enabled: s?.enabled ?? e.id === DEFAULT_ENABLED,
        params: { ...d.params, ...(s?.params ?? {}) },
        ui: { ...d.ui, ...(s?.ui ?? {}) },
      };
    }
    return out;
  }, [engines.data, prefs.data]);

  const save = useMutation({
    mutationFn: (next: IndPrefs) => api("/prefs/indicators", { method: "PUT", body: { value: next } }),
    onMutate: (next) => qc.setQueryData(["prefs"], (old: Record<string, unknown> | undefined) => ({ ...(old ?? {}), indicators: next })),
  });
  const update = (id: string, patch: Partial<IndState>) => save.mutate({ ...state, [id]: { ...state[id]!, ...patch } });

  const active = (engines.data ?? []).filter((e) => state[e.id]?.enabled);
  const runKey = (e: EngineOut) => paramsForRun(fieldsOf(e), state[e.id]!.params);
  const runs = useQueries({
    queries: active.map((e) => ({
      queryKey: ["run", e.id, symbol, live ? e.default_timeframe : engineTf(e, chartTf), JSON.stringify(runKey(e)), live?.source ?? "", live?.version ?? 0],
      // live: the collector's own run (source live:<instrument>), refetched when the server says outputs changed
      queryFn: live
        ? () => api<PlotsOut>(`/plots?engine_id=${e.id}&snapshot_id=${encodeURIComponent(live.source)}&timeframe=${e.default_timeframe}`).then((p) => p.run_id)
        : () => runEngine(e, symbol, runKey(e), engineTf(e, chartTf)),
      staleTime: Infinity,
    })),
  });
  const ready = active.map((e, i) => ({ e, runId: runs[i]?.data }));
  const outs = useQueries({
    queries: ready.flatMap(({ runId }) =>
      (["plots", "events", "overlays"] as const).map((k) => ({
        queryKey: [k, runId, live?.version ?? 0],
        queryFn: () => api<PlotsOut | EventsOut | OverlaysOut>(`/${k}?run_id=${runId}`),
        enabled: !!runId,
        staleTime: Infinity,
      })),
    ),
  });

  const status: Record<string, RunStatus> = {};
  const layers: PlotLayer[] = [];
  const overlays: El[] = [];
  const panels: { engine: EngineOut; panel: PlotsOut["panel"]; times: number[] }[] = [];
  active.forEach((e, i) => {
    const r = runs[i]!;
    status[e.id] = r.isError ? { state: "failed", error: (r.error as Error).message } : r.data ? { state: "ready", runId: r.data } : { state: "running" };
    const plots = outs[i * 3]?.data as PlotsOut | undefined;
    const ov = outs[i * 3 + 2]?.data as OverlaysOut | undefined;
    if (plots) {
      layers.push(...plotLayers(e, plots, TF_SEC[(live ? e.default_timeframe : engineTf(e, chartTf)) as Tf] ?? 300, state[e.id]!.ui).filter((l) => plotVisible(e.id, l.name, state[e.id]!.ui, state[e.id]!.params)));
      const ui = state[e.id]!.ui;
      // Balu: "Show Panel", NVS: "Show Table" (both default on); the card is hidden when switched off
      if (ui.show_panel !== false && ui.show_table !== false) panels.push({ engine: e, panel: plots.panel, times: plots.t });
    }
    if (ov) {
      const { ui, params } = state[e.id]!;
      for (const o of ov.overlays) {
        const shown = overlayFor(e.id, toEl(o), ui, params);
        if (shown) overlays.push(shown);
      }
    }
  });
  const colors = useMemo(() => {
    const c: Record<string, string> = {};
    for (const e of active) for (const [k, v] of Object.entries(state[e.id]!.ui)) if (k.startsWith("color_") && typeof v === "string") c[k.slice(6)] = v;
    return c;
  }, [active, state]);

  const enabledIds = active.map((e) => e.id);
  return { engines: engines.data ?? [], state, update, status, layers, overlays, panels, colors, enabledIds };
}
