import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { InstrumentOut } from "../api/schemas";
import { ChartPane } from "../chart/ChartPane";
import type { Tool } from "../chart/ChartView";
import { TFS, TF_LABEL, type Tf } from "../chart/geometry";
import { type ChartLayout, type LayoutN, type PaneState, type Sizes, fromPrefs, setLayoutN, toPrefs, updatePane } from "../chart/layout";
import { SplitLayout } from "../chart/SplitLayout";
import { OptionPicker } from "../chart/OptionPicker";
import { ReplayBar } from "../replay/ReplayBar";
import { useReplay } from "../replay/store";
import { activePane, useUi } from "../store";

const OPTION = "__option__"; // symbol-select entry that opens the option picker

const TOOLS: { id: Tool; label: string }[] = [
  { id: "select", label: "Select" },
  { id: "trendline", label: "Trend line" },
  { id: "hline", label: "Horizontal line" },
  { id: "rect", label: "Rectangle" },
  { id: "text", label: "Text" },
];

export function Chart() {
  const { chart, restored, set, setChart } = useUi();
  const { symbol, tf } = activePane({ chart });
  const [live, setLive] = useState(false);
  // indicator settings live in a sidebar next to the chart (never over the candles); remembered per browser
  const [showInd, setShowInd] = useState(() => { try { return localStorage.getItem("nifty.indicators.open") !== "0"; } catch { return true; } });
  const toggleInd = () => setShowInd((v) => { try { localStorage.setItem("nifty.indicators.open", v ? "0" : "1"); } catch { /* private mode */ } return !v; });
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: () => api<InstrumentOut[]>("/instruments") });
  const [times, setTimes] = useState<number[]>([]);
  const [tool, setTool] = useState<Tool>("select");
  const [picking, setPicking] = useState(false);
  const pane = activePane({ chart });
  // portal targets for the active pane's sidebar, engine cards and live banner
  const [sidebarSlot, setSidebarSlot] = useState<HTMLElement | null>(null);
  const [cardsSlot, setCardsSlot] = useState<HTMLElement | null>(null);
  const [bannerSlot, setBannerSlot] = useState<HTMLElement | null>(null);

  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });

  // restore the last layout (or the old single symbol / timeframe) once
  useEffect(() => {
    if (restored || !prefs.isSuccess) return;
    set({ restored: true, chart: fromPrefs(prefs.data["chart_layout"], prefs.data["chart"], { symbol, tf }) });
  }, [prefs.isSuccess, prefs.data, restored, set, symbol, tf]);

  const savePrefs = (l: ChartLayout) => {
    const p = toPrefs(l);
    void api(`/prefs/chart_layout`, { method: "PUT", body: { value: p.chart_layout } });
    void api(`/prefs/chart`, { method: "PUT", body: { value: p.chart } });
  };
  const pick = (next: Partial<{ symbol: string; tf: Tf }>) => {
    const patch: Partial<PaneState> = next.symbol ? { ...next, kind: "index", label: undefined } : next;
    const l = updatePane(chart, chart.active, patch);
    setChart(l);
    savePrefs(l);
  };

  const setLayout = (n: LayoutN) => {
    const l = setLayoutN(chart, n);
    setChart(l);
    savePrefs(l);
  };
  // read the latest layout from the store: drag events arrive faster than re-renders
  const onSizes = (sizes: Sizes, done: boolean) => {
    const l = { ...useUi.getState().chart, sizes };
    setChart(l);
    if (done) savePrefs(l);
  };

  // when a trading symbol is ambiguous (csv and kite NIFTY 50) the options carry instrument ids
  const ambiguous = (instruments.data ?? []).filter((x) => x.tradingsymbol === symbol);
  const selectValue = ambiguous.length > 1 ? ambiguous[0]!.instrument_id : symbol;
  const ready = restored || prefs.isError;
  return (
    <div className="chart-page">
      <div className="toolbar" role="toolbar" aria-label="Chart controls">
        <ReplayBar times={times} tf={tf} />
        <div className="seg" role="group" aria-label="Layout">
          {([1, 2, 3] as const).map((n) => (
            <button key={n} className={chart.layout === n ? "on" : ""} aria-pressed={chart.layout === n} data-testid={`layout-${n}`}
              title={n === 1 ? "One chart" : n === 2 ? "Two charts side by side" : "Three charts: one large, two stacked"} onClick={() => setLayout(n)}>
              {n === 1 ? "▣" : n === 2 ? "◫" : "⊞"} {n}
            </button>
          ))}
        </div>
        <div className="seg" role="group" aria-label="Mode">
          <button className={!live ? "on" : ""} onClick={() => setLive(false)} data-testid="mode-history">History</button>
          <button className={live ? "on" : ""} onClick={() => { useReplay.getState().exit(); setLive(true); }} data-testid="mode-live">Live</button>
        </div>
        <select value={pane.kind === "option" ? pane.symbol : selectValue} aria-label="Symbol"
          onChange={(e) => (e.target.value === OPTION ? setPicking(true) : pick({ symbol: e.target.value }))}>
          {pane.kind === "option" && <option value={pane.symbol}>{pane.label ?? pane.symbol}</option>}
          {(instruments.data ?? [{ tradingsymbol: symbol, instrument_id: symbol } as InstrumentOut]).map((i) => {
            const dup = (instruments.data ?? []).filter((x) => x.tradingsymbol === i.tradingsymbol).length > 1;
            return (
              <option key={i.instrument_id} value={dup ? i.instrument_id : i.tradingsymbol}>
                {dup ? i.instrument_id : i.tradingsymbol}
              </option>
            );
          })}
          <option value={OPTION}>Option…</option>
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
      <div className="slot" ref={setBannerSlot} />
      <div className="chart-row">
        {ready && (
          <SplitLayout layout={chart.layout} sizes={chart.sizes} onSizes={onSizes}>
            {chart.panes.map((pane, i) => (
          <ChartPane
            key={i}
            index={i}
            pane={pane}
            active={i === chart.active}
            live={live}
            tool={tool}
            onActivate={() => { if (i !== chart.active) setChart({ ...chart, active: i }); }}
            onToolDone={() => setTool("select")}
            {...(i === chart.active ? { onTimes: setTimes } : {})}
            sidebarSlot={showInd ? sidebarSlot : null}
            cardsSlot={cardsSlot}
            bannerSlot={bannerSlot}
          />
            ))}
          </SplitLayout>
        )}
        <div className="slot" ref={setSidebarSlot} />
      </div>
      <div className="cards" ref={setCardsSlot} />
      {picking && (
        <OptionPicker
          onClose={() => setPicking(false)}
          onPick={(id, label) => {
            setPicking(false);
            const l = updatePane(chart, chart.active, { symbol: id, kind: "option", label });
            setChart(l);
            savePrefs(l);
          }}
        />
      )}
    </div>
  );
}
