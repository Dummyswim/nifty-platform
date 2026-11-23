import {
  CandlestickSeries,
  type CandlestickData,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineType,
  AreaSeries,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
  type UTCTimestamp,
  createChart,
} from "lightweight-charts";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { BarsOut, DrawingData, DrawingKind, DrawingOut } from "../api/schemas";
import {
  type Cols, type Hit, type Pt, type Tf, type TP,
  fmtIst, hitTest, logicalToTime, mergeCols, movePoints, tickLabel, timeToLogical,
} from "./geometry";
import { type DrawItem, DrawingsPrimitive } from "./primitives";
import { type PlotLayer, revealPlot, splitRuns } from "../overlay/layers";
import { type El, pickOverlays } from "../overlay/pick";
import { OverlayPrimitive } from "../overlay/primitive";
import { TF_SEC, visibleCount } from "../replay/logic";

export type Tool = "select" | DrawingKind;

export interface ChartViewProps {
  symbol: string;
  tf: Tf;
  tool: Tool;
  drawings: DrawingOut[];
  onCreate: (kind: DrawingKind, data: DrawingData) => void;
  onUpdate: (id: string, data: DrawingData) => void;
  onDelete: (id: string) => void;
  onToolDone: () => void;
  plots?: PlotLayer[];
  overlays?: El[];
  overlayColors?: Record<string, string>;
  /** replay cursor (UTC epoch s); null/undefined = end of data */
  cursor?: number | null;
  /** scroll the view to this time span once (audit "open on chart") */
  focus?: { from: number; to: number; nonce: number } | null;
  /** called with the loaded bar start times (ascending) whenever they change */
  onTimes?: (times: number[]) => void;
}

const PAGE = 5000;
const LOAD_OLDER_AT = 40; // bars from the left edge that trigger an older-page fetch

const toCols = (b: BarsOut): Cols => ({ t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v });
const candles = (c: Cols): CandlestickData<Time>[] =>
  c.t.map((t, i) => ({ time: t as UTCTimestamp, open: c.o[i]!, high: c.h[i]!, low: c.l[i]!, close: c.c[i]! }));

interface Legend { t: number; o: number; h: number; l: number; c: number; v: number }

export function ChartView({
  symbol, tf, tool, drawings, onCreate, onUpdate, onDelete, onToolDone,
  plots = [], overlays = [], overlayColors, cursor = null, focus = null, onTimes,
}: ChartViewProps) {
  const box = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const prim = useRef(new DrawingsPrimitive());
  const ovPrim = useRef(new OverlayPrimitive());
  const plotSeries = useRef(new Map<string, ISeriesApi<"Line" | "Area" | "Histogram">>());
  const onTimesRef = useRef(onTimes);
  onTimesRef.current = onTimes;
  const cursorRef = useRef<number | null>(cursor);
  cursorRef.current = cursor;
  const cols = useRef<Cols>({ t: [], o: [], h: [], l: [], c: [], v: [] });
  const [nBars, setNBars] = useState(0);
  const [legend, setLegend] = useState<Legend | null>(null);
  const [error, setError] = useState("");
  const [entries, setEntries] = useState(0); // entry markers revealed at the cursor
  const [selected, setSelected] = useState<string | null>(null);
  const edits = useRef(new Map<string, TP[]>()); // live (unsaved) points while dragging
  const draft = useRef<DrawItem | null>(null);
  const drag = useRef<{ id: string; hit: Hit; lg: number; price: number; orig: TP[] } | null>(null);
  const props = useRef({ drawings, tool, selected, onCreate, onUpdate, onDelete, onToolDone });
  props.current = { drawings, tool, selected, onCreate, onUpdate, onDelete, onToolDone };

  const refresh = useCallback(() => {
    const items: DrawItem[] = props.current.drawings.map((d) => ({
      id: d.id, kind: d.kind, points: edits.current.get(d.id) ?? d.data.points, text: d.data.text ?? undefined, color: d.data.color ?? undefined,
    }));
    prim.current.set(items, cols.current.t, props.current.selected, draft.current);
  }, []);

  // chart lifetime (StrictMode mounts twice: cleanup must remove the first chart)
  useEffect(() => {
    const el = box.current!;
    const chart = createChart(el, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0b0e14" }, textColor: "#aab2c0", attributionLogo: false },
      grid: { vertLines: { color: "#161b26" }, horzLines: { color: "#161b26" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#252b3a" },
      localization: { timeFormatter: (t: Time) => fmtIst(t as number) },
      timeScale: {
        borderColor: "#252b3a", timeVisible: true, secondsVisible: false, rightOffset: 6,
        tickMarkFormatter: (t: Time, type: number) => tickLabel(t as number, type),
      },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#26a69a", downColor: "#ef5350", borderVisible: false, wickUpColor: "#26a69a", wickDownColor: "#ef5350",
      lastValueVisible: true, priceLineVisible: true,
    });
    series.attachPrimitive(ovPrim.current);
    series.attachPrimitive(prim.current);
    chartRef.current = chart;
    candleRef.current = series;
    const onMove = (p: MouseEventParams<Time>) => {
      const d = p.seriesData.get(series) as CandlestickData<Time> | undefined;
      if (!d || p.time === undefined) return setLegend(null);
      const i = cols.current.t.indexOf(p.time as number);
      setLegend({ t: p.time as number, o: d.open, h: d.high, l: d.low, c: d.close, v: i >= 0 ? cols.current.v[i]! : 0 });
    };
    chart.subscribeCrosshairMove(onMove);
    return () => {
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      plotSeries.current.clear();
      chartRef.current = candleRef.current = volRef.current = null;
    };
  }, []);

  // data for (symbol, tf): newest page, then older pages by cursor
  useEffect(() => {
    const chart = chartRef.current!;
    const series = candleRef.current!;
    let cancelled = false;
    let cursor: number | null = null;
    let loading = false;
    let kind = "absent";
    cols.current = { t: [], o: [], h: [], l: [], c: [], v: [] };
    setNBars(0);
    setError("");

    const apply = (c: Cols) => {
      cols.current = c;
      onTimesRef.current?.(c.t);
      const n = visibleCount(c.t, tf, cursorRef.current);
      series.setData(candles(c).slice(0, n));
      if (kind !== "absent") {
        volRef.current ??= chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol" }, 1);
        volRef.current.setData(c.t.slice(0, n).map((t, i) => ({ time: t as UTCTimestamp, value: c.v[i]!, color: c.c[i]! >= c.o[i]! ? "#26a69a66" : "#ef535066" })));
      } else if (volRef.current) {
        chart.removeSeries(volRef.current);
        volRef.current = null;
      }
      setNBars(c.t.length);
      refresh();
    };
    const url = (extra: string) => `/bars?symbol=${encodeURIComponent(symbol)}&tf=${tf}&limit=${PAGE}${extra}`;

    api<BarsOut>(url(""))
      .then((b) => {
        if (cancelled) return;
        kind = b.volume_kind;
        cursor = b.next_cursor ?? null;
        apply(toCols(b));
        chart.timeScale().scrollToRealTime();
        const last = b.t.length - 1;
        if (last >= 0) setLegend({ t: b.t[last]!, o: b.o[last]!, h: b.h[last]!, l: b.l[last]!, c: b.c[last]!, v: b.v[last]! });
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : "failed to load bars"));

    const onRange = (r: { from: number; to: number } | null) => {
      if (!r || cursor === null || loading || r.from > LOAD_OLDER_AT) return;
      loading = true;
      api<BarsOut>(url(`&cursor=${cursor}`))
        .then((b) => {
          if (cancelled) return;
          cursor = b.next_cursor ?? null;
          const before = cols.current.t.length;
          const merged = mergeCols(toCols(b), cols.current);
          const added = merged.t.length - before;
          apply(merged);
          const cur = chart.timeScale().getVisibleLogicalRange();
          if (cur && added > 0) chart.timeScale().setVisibleLogicalRange({ from: cur.from + added, to: cur.to + added });
        })
        .catch(() => undefined)
        .finally(() => (loading = false));
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    return () => {
      cancelled = true;
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
    };
  }, [symbol, tf, refresh]);

  useEffect(refresh, [drawings, selected, refresh]);

  // replay: reveal bars by cursor (never refetches)
  useEffect(() => {
    const c = cols.current;
    if (!candleRef.current || c.t.length === 0) return;
    const n = visibleCount(c.t, tf, cursor);
    candleRef.current.setData(candles(c).slice(0, n));
    volRef.current?.setData(c.t.slice(0, n).map((t, i) => ({ time: t as UTCTimestamp, value: c.v[i]!, color: c.c[i]! >= c.o[i]! ? "#26a69a66" : "#ef535066" })));
    if (cursor !== null) chartRef.current?.timeScale().scrollToRealTime();
    const last = n - 1;
    if (last >= 0) setLegend({ t: c.t[last]!, o: c.o[last]!, h: c.h[last]!, l: c.l[last]!, c: c.c[last]!, v: c.v[last]! });
  }, [cursor, tf]);

  // engine plots as series (line/step/hist/area; overlay pane or own pane). Step plots are drawn as
  // one series per contiguous run so a trade's stop/target does not connect to the next trade's.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    const map = plotSeries.current;
    const wanted = new Map<string, { p: PlotLayer; data: { time: number; value?: number }[] }>();
    for (const p of plots) {
      const pts = revealPlot(p, cursor);
      if (p.kind === "step") splitRuns(pts).forEach((run, i) => wanted.set(`${p.key}#${i}`, { p, data: run }));
      else wanted.set(p.key, { p, data: pts });
    }
    for (const [k, s] of map) if (!wanted.has(k)) { chart.removeSeries(s); map.delete(k); }
    const panes = new Map<string, number>();
    let own = 1 + (volRef.current ? 1 : 0);
    for (const [k, { p, data }] of wanted) {
      let s = map.get(k);
      if (!s) {
        if (!panes.has(p.key)) panes.set(p.key, p.pane === "own" ? own++ : 0);
        const pane = panes.get(p.key)!;
        const base = { color: p.color, lastValueVisible: false, priceLineVisible: false };
        s = (
          p.kind === "hist" ? chart.addSeries(HistogramSeries, { color: p.color, priceLineVisible: false, lastValueVisible: false }, pane)
          : p.kind === "area" ? chart.addSeries(AreaSeries, { lineColor: p.color, topColor: p.color + "55", bottomColor: "transparent", ...base }, pane)
          : chart.addSeries(LineSeries, { ...base, lineWidth: 2, lineType: p.kind === "step" ? LineType.WithSteps : LineType.Simple }, pane)
        ) as ISeriesApi<"Line" | "Area" | "Histogram">;
        map.set(k, s);
      }
      s.setData(data as never);
    }
  }, [plots, cursor]);

  // overlay elements picked for the cursor
  useEffect(() => {
    const t = cols.current.t;
    const end = t.length ? t[t.length - 1]! + TF_SEC[tf] : 0;
    const picked = pickOverlays(overlays, cursor, end);
    ovPrim.current.set(picked, t, overlayColors ?? {});
    setEntries(picked.filter((o) => o.kind === "marker" && o.id.endsWith(":entry")).length);
  }, [overlays, cursor, nBars, tf, overlayColors]);

  // one-shot focus on a time span
  useEffect(() => {
    if (!focus || nBars === 0) return;
    const a = timeToLogical(cols.current.t, focus.from);
    const b = timeToLogical(cols.current.t, focus.to);
    if (a !== null && b !== null) chartRef.current?.timeScale().setVisibleLogicalRange({ from: a - 12, to: b + 12 });
  }, [focus?.nonce, nBars]); // eslint-disable-line react-hooks/exhaustive-deps

  // delete key
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if ((e.key === "Delete" || e.key === "Backspace") && props.current.selected && tag !== "INPUT" && tag !== "TEXTAREA") {
        props.current.onDelete(props.current.selected);
        setSelected(null);
      }
      if (e.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ---- pointer interaction for drawings ------------------------------------------------------
  const local = (e: React.PointerEvent): Pt => {
    const r = box.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const toTP = (p: Pt): TP | null => {
    const lg = chartRef.current!.timeScale().coordinateToLogical(p.x);
    const price = candleRef.current!.coordinateToPrice(p.y);
    const t = lg === null ? null : logicalToTime(cols.current.t, lg);
    return t === null || price === null ? null : { t, p: price };
  };
  const lock = (on: boolean) => chartRef.current?.applyOptions({ handleScroll: !on, handleScale: !on });

  const onDown = (e: React.PointerEvent) => {
    if (e.button !== 0 || !chartRef.current) return;
    const pt = local(e);
    const { tool: tl, drawings: ds } = props.current;
    if (tl === "select") {
      for (const d of [...ds].reverse()) {
        const s = prim.current.shapeOf({ id: d.id, kind: d.kind, points: edits.current.get(d.id) ?? d.data.points, text: d.data.text ?? undefined });
        const hit = s && hitTest(s, pt);
        if (!hit) continue;
        const lg = chartRef.current.timeScale().coordinateToLogical(pt.x);
        const price = candleRef.current!.coordinateToPrice(pt.y);
        if (lg === null || price === null) return;
        setSelected(d.id);
        drag.current = { id: d.id, hit, lg, price, orig: d.data.points };
        box.current!.setPointerCapture(e.pointerId);
        lock(true);
        return;
      }
      setSelected(null);
      return;
    }
    const tp = toTP(pt);
    if (!tp) return;
    if (tl === "hline") {
      props.current.onCreate("hline", { points: [tp] });
      props.current.onToolDone();
    } else if (tl === "text") {
      const text = window.prompt("Text", "Note");
      if (text) props.current.onCreate("text", { points: [tp], text });
      props.current.onToolDone();
    } else {
      draft.current = { id: "draft", kind: tl, points: [tp, tp] };
      box.current!.setPointerCapture(e.pointerId);
      lock(true);
      refresh();
    }
  };
  const onMove = (e: React.PointerEvent) => {
    const pt = local(e);
    if (draft.current) {
      const tp = toTP(pt);
      if (tp) draft.current = { ...draft.current, points: [draft.current.points[0]!, tp] };
      refresh();
    } else if (drag.current) {
      const d = drag.current;
      const lg = chartRef.current!.timeScale().coordinateToLogical(pt.x);
      const price = candleRef.current!.coordinateToPrice(pt.y);
      if (lg === null || price === null) return;
      edits.current.set(d.id, movePoints(cols.current.t, d.orig, d.hit, lg - d.lg, price - d.price));
      refresh();
    }
  };
  const onUp = (e: React.PointerEvent) => {
    if (draft.current) {
      const d = draft.current;
      draft.current = null;
      const [a, b] = d.points;
      const moved = a && b && (Math.abs((timeToLogical(cols.current.t, a.t) ?? 0) - (timeToLogical(cols.current.t, b.t) ?? 0)) > 0.2 || Math.abs(a.p - b.p) > 0);
      if (moved && d.kind !== "hline" && d.kind !== "text") props.current.onCreate(d.kind, { points: d.points });
      props.current.onToolDone();
      lock(false);
      refresh();
    } else if (drag.current) {
      const d = drag.current;
      drag.current = null;
      const pts = edits.current.get(d.id);
      edits.current.delete(d.id);
      const cur = props.current.drawings.find((x) => x.id === d.id);
      if (pts && cur) props.current.onUpdate(d.id, { ...cur.data, points: pts });
      lock(false);
      refresh();
    }
    if (box.current?.hasPointerCapture(e.pointerId)) box.current.releasePointerCapture(e.pointerId);
  };

  const shown = legend;
  return (
    <div className="chart-wrap">
      <div
        ref={box}
        className={`chart ${tool === "select" ? "" : "drawing"}`}
        data-testid="chart"
        data-bars={nBars}
        data-tf={tf}
        data-symbol={symbol}
        data-drawings={drawings.length}
        data-overlays={overlays.length}
        data-entry-markers={entries}
        data-shown={visibleCount(cols.current.t, tf, cursor)}
        data-plots={plots.length}
        data-cursor={cursor ?? ""}
        onPointerDownCapture={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      />
      <div className="legend" data-testid="legend">
        <strong>{symbol}</strong> · {tf}
        {shown && (
          <span>
            {" "}
            {fmtIst(shown.t)} O <b data-testid="legend-o">{shown.o.toFixed(2)}</b> H <b>{shown.h.toFixed(2)}</b> L{" "}
            <b>{shown.l.toFixed(2)}</b> C <b data-testid="legend-c">{shown.c.toFixed(2)}</b>
          </span>
        )}
      </div>
      {error && <p className="chart-error" role="alert">{error}</p>}
    </div>
  );
}

