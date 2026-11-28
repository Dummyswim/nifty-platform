import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api/client";
import type { DrawingData, DrawingKind, DrawingOut, InstrumentOut } from "../api/schemas";
import { ContextBox, ContextToggle } from "../context/ContextBox";
import { useMarketContext } from "../context/useMarketContext";
import { EnginePanel } from "../indicators/EnginePanel";
import { IndicatorPanel } from "../indicators/IndicatorPanel";
import { useIndicators } from "../indicators/useIndicators";
import { banner } from "../live/messages";
import { useLiveStream } from "../live/useLiveStream";
import { useReplay } from "../replay/store";
import { useUi } from "../store";
import { ChartView, type Tool } from "./ChartView";
import type { PaneState } from "./layout";
import { paneNote } from "./optionPane";

export interface ChartPaneProps {
  index: number;
  pane: PaneState;
  active: boolean;
  live: boolean;
  tool: Tool;
  onActivate: () => void;
  onToolDone: () => void;
  /** only the active pane reports its bar times (replay bar) */
  onTimes?: (t: number[]) => void;
  /** where the active pane renders its Indicators sidebar / engine cards / live banner (null = hidden) */
  sidebarSlot: HTMLElement | null;
  cardsSlot: HTMLElement | null;
  bannerSlot: HTMLElement | null;
}


/** One chart: its own instrument, timeframe, drawings, indicators and live stream. */
export function ChartPane(p: ChartPaneProps) {
  const { symbol, tf } = p.pane;
  const focus = useUi((s) => s.focus);
  const cursor = useReplay((r) => r.cursor);
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: () => api<InstrumentOut[]>("/instruments") });
  const inst = instruments.data?.find((i) => i.tradingsymbol === symbol || i.instrument_id === symbol);
  const iid = inst?.instrument_id;
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  const niftyIndex = p.pane.kind === "index" && inst?.tradingsymbol === "NIFTY 50";
  const showIv = niftyIndex && prefs.data?.["context.show_iv"] !== false;
  const showOi = niftyIndex && prefs.data?.["context.show_oi"] !== false;
  const istDate = cursor === null ? undefined : new Date((cursor + 19800) * 1000).toISOString().slice(0, 10);
  const mctxIv = useMarketContext("NIFTY", p.live, istDate, "iv", showIv);
  const mctxOi = useMarketContext("NIFTY", p.live, istDate, "oi", showOi);
  const [ver, setVer] = useState(0); // bumped by the stream when engine outputs changed
  // option contracts: the collector runs no engines for them, so Live re-runs the History path per finalized bar
  const [finalized, setFinalized] = useState(0);
  const isOption = p.pane.kind === "option";
  const ind = useIndicators(symbol, tf, p.live && iid && !isOption ? { source: `live:${iid}`, version: ver } : null, isOption ? finalized : 0);
  const [nBars, setNBars] = useState(-1);
  const myFocus = focus && focus.pane === p.index ? focus : null;
  const overlays = useMemo(() => [...ind.overlays, ...(myFocus?.extra ?? [])], [ind.overlays, myFocus]);
  const sub = useLiveStream({ instrument: symbol, timeframe: tf, engines: ind.enabledIds, enabled: p.live });
  useEffect(() => setVer(sub.version), [sub.version]);
  useEffect(() => {
    if (isOption && sub.bars && !sub.bars.provisional) setFinalized((n) => n + 1);
  }, [isOption, sub.bars]);
  // the replay bar steps the active pane's bars: hand them over whenever this pane becomes active
  const onTimes = p.onTimes;
  const lastTimes = useRef<number[]>([]);
  const reportTimes = (t: number[]) => { lastTimes.current = t; setNBars(t.length); onTimes?.(t); };
  useEffect(() => { if (p.active) onTimes?.(lastTimes.current); }, [p.active, onTimes]);
  const note = nBars < 0 ? null : paneNote(p.pane.kind, nBars);
  const bn = banner(sub.state, sub.socket);

  const qc = useQueryClient();
  const key = ["drawings", symbol];
  const drawings = useQuery({ queryKey: key, queryFn: () => api<DrawingOut[]>(`/drawings?symbol=${encodeURIComponent(symbol)}`) });
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

  return (
    <div className={`pane ${p.active ? "active" : ""}`} data-testid="pane" data-active={p.active} data-index={p.index} onPointerDownCapture={p.onActivate}>
      <ChartView
        symbol={symbol}
        tf={tf}
        tool={p.active ? p.tool : "select"}
        drawings={drawings.data ?? []}
        onCreate={(kind, data) => create.mutate({ kind, data })}
        onUpdate={(id, data) => update.mutate({ id, data })}
        onDelete={(id) => remove.mutate(id)}
        onToolDone={p.onToolDone}
        plots={ind.layers}
        overlays={overlays}
        overlayColors={ind.colors}
        cursor={cursor}
        focus={myFocus}
        onTimes={reportTimes}
        title={p.pane.label}
        liveBars={p.live ? sub.bars : null}
        syncIndex={p.index}
        keysEnabled={p.active}
      />
      {(showIv || showOi) && (
        <div className="context-stack">
          {showIv && <ContextBox writing="iv" data={mctxIv.data} error={mctxIv.error} cursor={cursor} />}
          {showOi && <ContextBox writing="oi" data={mctxOi.data} error={mctxOi.error} cursor={cursor} />}
        </div>
      )}
      {note && <div className="pane-note" data-testid="pane-note">{p.pane.label ?? symbol}: {note}. Option charts show only what the live collector recorded.</div>}
      {p.active && p.live && p.bannerSlot && createPortal(
        <div className={`banner ${bn.level}`} role="status" data-testid="live-banner" data-state={sub.state ?? ""}>
          {bn.text}
          {bn.connectKite && <button className="ghost" onClick={() => useUi.getState().set({ page: "settings" })}>Connect Kite</button>}
        </div>,
        p.bannerSlot,
      )}
      {p.active && p.sidebarSlot && createPortal(
        <div className="side">
          {niftyIndex && <><ContextToggle writing="iv" /><ContextToggle writing="oi" /></>}
          <IndicatorPanel engines={ind.engines} state={ind.state} status={ind.status} update={ind.update} />
        </div>,
        p.sidebarSlot,
      )}
      {p.active && p.cardsSlot && createPortal(
        ind.panels.map((x) => <EnginePanel key={x.engine.id} id={x.engine.id} panel={x.panel} atEnd={cursor === null} />),
        p.cardsSlot,
      )}
    </div>
  );
}
