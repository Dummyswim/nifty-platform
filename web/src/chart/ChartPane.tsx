import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { create } from "zustand";
import { api } from "../api/client";
import type { DrawingData, DrawingKind, DrawingOut, InstrumentOut } from "../api/schemas";
import { EnginePanel } from "../indicators/EnginePanel";
import { IndicatorPanel } from "../indicators/IndicatorPanel";
import { useIndicators } from "../indicators/useIndicators";
import { banner } from "../live/messages";
import { useLiveStream } from "../live/useLiveStream";
import { useReplay } from "../replay/store";
import { useUi } from "../store";
import { ChartView, type Tool } from "./ChartView";
import type { PaneState } from "./layout";

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

/** The pane the pointer is over and its crosshair time; the other panes follow it. A pane's
 *  "pointer left" only resets it when that pane still owns it (leave can arrive after the next pane's move). */
const useHover = create<{ t: number | null; from: number }>(() => ({ t: null, from: -1 }));

/** One chart: its own instrument, timeframe, drawings, indicators and live stream. */
export function ChartPane(p: ChartPaneProps) {
  const { symbol, tf } = p.pane;
  const focus = useUi((s) => s.focus);
  const syncTime = useHover((h) => (h.from === p.index ? undefined : h.t));
  const cursor = useReplay((r) => r.cursor);
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: () => api<InstrumentOut[]>("/instruments") });
  const iid = instruments.data?.find((i) => i.tradingsymbol === symbol || i.instrument_id === symbol)?.instrument_id;
  const [ver, setVer] = useState(0); // bumped by the stream when engine outputs changed
  const ind = useIndicators(symbol, tf, p.live && iid ? { source: `live:${iid}`, version: ver } : null);
  const myFocus = p.active ? focus : null;
  const overlays = useMemo(() => [...ind.overlays, ...(myFocus?.extra ?? [])], [ind.overlays, myFocus]);
  const sub = useLiveStream({ instrument: symbol, timeframe: tf, engines: ind.enabledIds, enabled: p.live });
  useEffect(() => setVer(sub.version), [sub.version]);
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
        {...(p.onTimes ? { onTimes: p.onTimes } : {})}
        liveBars={p.live ? sub.bars : null}
        syncTime={syncTime}
        onCrosshairTime={(t) => useHover.setState((h) => (t === null && h.from !== p.index ? h : { t, from: p.index }))}
      />
      {p.active && p.live && p.bannerSlot && createPortal(
        <div className={`banner ${bn.level}`} role="status" data-testid="live-banner" data-state={sub.state ?? ""}>
          {bn.text}
          {bn.connectKite && <button className="ghost" onClick={() => useUi.getState().set({ page: "settings" })}>Connect Kite</button>}
        </div>,
        p.bannerSlot,
      )}
      {p.active && p.sidebarSlot && createPortal(
        <IndicatorPanel engines={ind.engines} state={ind.state} status={ind.status} update={ind.update} />,
        p.sidebarSlot,
      )}
      {p.active && p.cardsSlot && createPortal(
        ind.panels.map((x) => <EnginePanel key={x.engine.id} id={x.engine.id} panel={x.panel} atEnd={cursor === null} />),
        p.cardsSlot,
      )}
    </div>
  );
}
