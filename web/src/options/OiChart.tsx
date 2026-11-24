import { ColorType, LineSeries, type UTCTimestamp, createChart } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { fmtIst, tickLabel } from "../chart/geometry";

/** Open-interest line (last recorded OI per minute) under the contract chart. */
export function OiChart({ t, v }: { t: number[]; v: number[] }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const chart = createChart(el.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "#0b0e14" }, textColor: "#aab2c0", attributionLogo: false },
      grid: { vertLines: { color: "#161b26" }, horzLines: { color: "#161b26" } },
      localization: { timeFormatter: (x: unknown) => fmtIst(x as number) },
      timeScale: { timeVisible: true, tickMarkFormatter: (x: unknown, type: number) => tickLabel(x as number, type) },
    });
    const s = chart.addSeries(LineSeries, { color: "#4c8dff", lineWidth: 2 });
    s.setData(t.map((x, i) => ({ time: x as UTCTimestamp, value: v[i]! })));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [t, v]);
  return <div ref={el} className="oi-chart" data-testid="oi-chart" data-points={t.length} />;
}
