import type { IChartApi, IPrimitivePaneRenderer, IPrimitivePaneView, ISeriesApi, ISeriesPrimitive, Logical, SeriesAttachedParameter, SeriesType, Time } from "lightweight-charts";
import { timeToLogical } from "../chart/geometry";
import type { BandFill } from "./layers";

/** Shaded areas between two plot lines (Pine `fill`), drawn under the candles' series. */
export class FillPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private request: (() => void) | null = null;
  private fills: BandFill[] = [];
  private times: number[] = [];

  attached(p: SeriesAttachedParameter<Time>): void {
    this.chart = p.chart as IChartApi;
    this.series = p.series;
    this.request = p.requestUpdate;
  }
  detached(): void {
    this.chart = this.series = this.request = null;
  }
  set(fills: BandFill[], times: number[]): void {
    this.fills = fills;
    this.times = times;
    this.request?.();
  }

  private view: IPrimitivePaneView = {
    zOrder: () => "bottom",
    renderer: (): IPrimitivePaneRenderer => ({
      draw: (target) => {
        const chart = this.chart, series = this.series;
        if (!chart || !series) return;
        const ts = chart.timeScale();
        const x = (t: number) => {
          const lg = timeToLogical(this.times, t);
          return lg === null ? null : ts.logicalToCoordinate(lg as Logical);
        };
        target.useMediaCoordinateSpace(({ context: ctx }) => {
          for (const f of this.fills) {
            ctx.fillStyle = f.color;
            for (const run of f.pts) {
              if (run.length < 2) continue;
              ctx.beginPath();
              let ok = true;
              run.forEach((p, i) => {
                const px = x(p.time), py = series.priceToCoordinate(p.hi);
                if (px === null || py === null) { ok = false; return; }
                if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
              });
              for (let i = run.length - 1; i >= 0; i--) {
                const p = run[i]!, px = x(p.time), py = series.priceToCoordinate(p.lo);
                if (px === null || py === null) { ok = false; break; }
                ctx.lineTo(px, py);
              }
              if (ok) { ctx.closePath(); ctx.fill(); }
            }
          }
        });
      },
    }),
  };
  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }
}
