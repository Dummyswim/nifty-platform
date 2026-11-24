import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "../api/client";
import type { DrawingData, DrawingKind, DrawingOut, InstrumentOut } from "../api/schemas";
import { ChartView, type Tool } from "../chart/ChartView";
import { TFS, TF_LABEL, type Tf } from "../chart/geometry";
import { useUi } from "../store";
import { useMemo, useState } from "react";
import { EnginePanel } from "../indicators/EnginePanel";
import { IndicatorPanel } from "../indicators/IndicatorPanel";
import { useIndicators } from "../indicators/useIndicators";
import { ReplayBar } from "../replay/ReplayBar";
import { useReplay } from "../replay/store";
import { banner } from "../live/messages";
import { useLiveStream } from "../live/useLiveStream";

const TOOLS: { id: Tool; label: string }[] = [
  { id: "select", label: "Select" },
  { id: "trendline", label: "Trend line" },
  { id: "hline", label: "Horizontal line" },
  { id: "rect", label: "Rectangle" },
  { id: "text", label: "Text" },
];

export function Chart() {
  const { symbol, tf, restored, focus, set } = useUi();
  const cursor = useReplay((r) => r.cursor);
  const [live, setLive] = useState(false);
  // indicator settings live in a sidebar next to the chart (never over the candles); remembered per browser
  const [showInd, setShowInd] = useState(() => { try { return localStorage.getItem("nifty.indicators.open") !== "0"; } catch { return true; } });
  const toggleInd = () => setShowInd((v) => { try { localStorage.setItem("nifty.indicators.open", v ? "0" : "1"); } catch { /* private mode */ } return !v; });
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: () => api<InstrumentOut[]>("/instruments") });
  const iid = instruments.data?.find((i) => i.tradingsymbol === symbol || i.instrument_id === symbol)?.instrument_id;
  const [ver, setVer] = useState(0); // bumped by the stream when engine outputs changed
  const ind = useIndicators(symbol, tf, live && iid ? { source: `live:${iid}`, version: ver } : null);
  const [times, setTimes] = useState<number[]>([]);
  const overlays = useMemo(() => [...ind.overlays, ...(focus?.extra ?? [])], [ind.overlays, focus]);
  const qc = useQueryClient();
  const [tool, setTool] = useState<Tool>("select");

  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  const key = ["drawings", symbol];
  const drawings = useQuery({ queryKey: key, queryFn: () => api<DrawingOut[]>(`/drawings?symbol=${encodeURIComponent(symbol)}`) });

  // restore the last symbol / timeframe once
  useEffect(() => {
    if (restored || !prefs.isSuccess) return;
    const p = prefs.data["chart"] as { symbol?: string; tf?: Tf } | undefined;
    set({ restored: true, ...(p?.symbol ? { symbol: p.symbol } : {}), ...(p?.tf && TFS.includes(p.tf) ? { tf: p.tf } : {}) });
  }, [prefs.isSuccess, prefs.data, restored, set]);

  const sub = useLiveStream({ instrument: symbol, timeframe: tf, engines: ind.enabledIds, enabled: live });
  useEffect(() => setVer(sub.version), [sub.version]);
  const bn = banner(sub.state, sub.socket);
  const savePref = (next: { symbol: string; tf: Tf }) =>
    void api(`/prefs/chart`, { method: "PUT", body: { value: next } });

  const create = useMutation({
    mutationFn: (v: { kind: DrawingKind; data: DrawingData }) => api<DrawingOut>("/drawings", { body: { symbol, kind: v.kind, data: v.data } }),
    onSuccess: (d) => qc.setQueryData<DrawingOut[]>(key, (old) => [...(old ?? []), d]),
  });
  const update = useMutation({
    mutationFn: (v: { id: string; data: DrawingData }) => api(`/drawings/${v.id}`, { method: "PUT", body: v.data }),
    onMutate: (v) => qc.setQueryData<DrawingOut[]>(key, (old) => (old ?? []).map((d) => (d.id === v.id ? { ...d, data: v.data } : d))),
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/drawings/${id}`, { method: "DELETE" }),
    onMutate: (id) => qc.setQueryData<DrawingOut[]>(key, (old) => (old ?? []).filter((d) => d.id !== id)),
  });

  const pick = (next: Partial<{ symbol: string; tf: Tf }>) => {
    const n = { symbol, tf, ...next };
    set(n);
    savePref(n);
  };

  // when a trading symbol is ambiguous (csv and kite NIFTY 50) the options carry instrument ids
  const ambiguous = (instruments.data ?? []).filter((x) => x.tradingsymbol === symbol);
  const selectValue = ambiguous.length > 1 ? ambiguous[0]!.instrument_id : symbol;
  const ready = restored || prefs.isError;
  return (
    <div className="chart-page">
      <div className="toolbar" role="toolbar" aria-label="Chart controls">
        <ReplayBar times={times} tf={tf} />
        <div className="seg" role="group" aria-label="Mode">
          <button className={!live ? "on" : ""} onClick={() => setLive(false)} data-testid="mode-history">History</button>
          <button className={live ? "on" : ""} onClick={() => { useReplay.getState().exit(); setLive(true); }} data-testid="mode-live">Live</button>
        </div>
        <select value={selectValue} onChange={(e) => pick({ symbol: e.target.value })} aria-label="Symbol">
          {(instruments.data ?? [{ tradingsymbol: symbol, instrument_id: symbol } as InstrumentOut]).map((i) => {
            const dup = (instruments.data ?? []).filter((x) => x.tradingsymbol === i.tradingsymbol).length > 1;
            return (
              <option key={i.instrument_id} value={dup ? i.instrument_id : i.tradingsymbol}>
                {dup ? i.instrument_id : i.tradingsymbol}
              </option>
            );
          })}
        </select>
        <div className="seg" role="group" aria-label="Timeframe">
          {TFS.map((t) => (
            <button key={t} className={t === tf ? "on" : ""} aria-pressed={t === tf} data-tf={t} onClick={() => pick({ tf: t })}>
              {TF_LABEL[t]}
            </button>
          ))}
        </div>
        <button className={showInd ? "on" : ""} aria-pressed={showInd} onClick={toggleInd} data-testid="toggle-indicators">Indicators</button>
        <div className="seg" role="group" aria-label="Drawing tools">
          {TOOLS.map((t) => (
            <button key={t.id} className={t.id === tool ? "on" : ""} aria-pressed={t.id === tool} data-tool={t.id} onClick={() => setTool(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
      </div>
      {live && (
        <div className={`banner ${bn.level}`} role="status" data-testid="live-banner" data-state={sub.state ?? ""}>
          {bn.text}
          {bn.connectKite && <button className="ghost" onClick={() => useUi.getState().set({ page: "settings" })}>Connect Kite</button>}
        </div>
      )}
      <div className="chart-row">
      {ready && (
        <ChartView
          symbol={symbol}
          tf={tf}
          tool={tool}
          drawings={drawings.data ?? []}
          onCreate={(kind, data) => create.mutate({ kind, data })}
          onUpdate={(id, data) => update.mutate({ id, data })}
          onDelete={(id) => remove.mutate(id)}
          onToolDone={() => setTool("select")}
          plots={ind.layers}
          overlays={overlays}
          overlayColors={ind.colors}
          cursor={cursor}
          focus={focus}
          onTimes={setTimes}
          liveBars={live ? sub.bars : null}
        />
      )}
      {showInd && <IndicatorPanel engines={ind.engines} state={ind.state} status={ind.status} update={ind.update} />}
      </div>
      <div className="cards">
        {ind.panels.map((p) => <EnginePanel key={p.engine.id} id={p.engine.id} panel={p.panel} atEnd={cursor === null} />)}
      </div>
    </div>
  );
}
