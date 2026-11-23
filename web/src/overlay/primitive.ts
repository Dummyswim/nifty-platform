import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";
import { timeToLogical } from "../chart/geometry";
import { type El, roleColor, zoneStyle } from "./pick";

/** Draws every OverlayElement kind (line step_line hline band zone marker label region) as one
 *  series primitive; kinds are separate draw functions below. Elements are already picked for the
 *  cursor (`pickOverlays`), so this only maps (time, price) to pixels. */
export class OverlayPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private request: (() => void) | null = null;
  els: El[] = [];
  times: number[] = [];
  colors: Record<string, string> = {};

  attached(p: SeriesAttachedParameter<Time>): void {
    this.chart = p.chart as IChartApi;
    this.series = p.series;
    this.request = p.requestUpdate;
  }
  detached(): void {
    this.chart = this.series = this.request = null;
  }
  set(els: El[], times: number[], colors: Record<string, string>): void {
    this.els = els;
    this.times = times;
    this.colors = colors;
    this.request?.();
  }

  private x = (t: number): number | null => {
    const lg = timeToLogical(this.times, t);
    return lg === null || !this.chart ? null : this.chart.timeScale().logicalToCoordinate(lg as Logical);
  };
  private y = (p: number | null): number | null =>
    p === null || !this.series ? null : this.series.priceToCoordinate(p);

  private view: IPrimitivePaneView = {
    zOrder: () => "normal",
    renderer: (): IPrimitivePaneRenderer => ({
      draw: (target) => {
        target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
          for (const e of this.els) {
            const col = roleColor(e.style.role, this.colors);
            ctx.save();
            ctx.strokeStyle = ctx.fillStyle = col;
            ctx.lineWidth = Number(e.style.width ?? 1.5);
            if (e.style.dashed) ctx.setLineDash([5, 4]);
            this.drawOne(ctx, e, col, mediaSize.width, mediaSize.height);
            ctx.restore();
          }
        });
      },
    }),
  };

  private drawOne(ctx: CanvasRenderingContext2D, e: El, col: string, w: number, h: number): void {
    const x0 = this.x(e.t0);
    const x1 = e.t1 === null ? null : this.x(e.t1);
    const y0 = this.y(e.p0);
    const y1 = this.y(e.p1 ?? e.p0);
    switch (e.kind) {
      case "line":
      case "step_line":
        if (x0 === null || x1 === null || y0 === null || y1 === null) return;
        ctx.beginPath();
        ctx.moveTo(x0, y0);
        if (e.kind === "step_line") ctx.lineTo(x1, y0);
        ctx.lineTo(x1, y1);
        ctx.stroke();
        return;
      case "hline":
        if (y0 === null) return;
        ctx.beginPath();
        ctx.moveTo(x0 ?? 0, y0);
        ctx.lineTo(x1 ?? w, y0);
        ctx.stroke();
        return;
      case "band":
      case "zone": {
        const top = this.y(typeof e.meta.top === "number" ? e.meta.top : e.p0);
        const bot = this.y(typeof e.meta.bot === "number" ? e.meta.bot : (e.p1 ?? e.p0));
        if (x0 === null || x1 === null || top === null || bot === null) return;
        const zs = e.kind === "zone" ? zoneStyle(e.meta) : { fillAlpha: 0.15, dashed: false };
        if (zs.dashed) ctx.setLineDash([5, 4]);
        ctx.globalAlpha = zs.fillAlpha;
        ctx.fillRect(x0, Math.min(top, bot), x1 - x0, Math.abs(bot - top));
        ctx.globalAlpha = 1;
        ctx.strokeRect(x0, Math.min(top, bot), x1 - x0, Math.abs(bot - top));
        if (e.text) ctx.fillText(e.text, x0 + 3, Math.min(top, bot) + 11);
        return;
      }
      case "region":
        if (x0 === null || x1 === null) return;
        ctx.globalAlpha = 0.07;
        ctx.fillRect(x0, 0, x1 - x0, h);
        return;
      case "marker": {
        if (x0 === null || y0 === null) return;
        const up = ["bull", "buy", "demand"].includes(String(e.style.role));
        const down = ["bear", "sell", "supply"].includes(String(e.style.role));
        ctx.beginPath();
        if (up) {
          ctx.moveTo(x0, y0 + 2);
          ctx.lineTo(x0 - 5, y0 + 11);
          ctx.lineTo(x0 + 5, y0 + 11);
        } else if (down) {
          ctx.moveTo(x0, y0 - 2);
          ctx.lineTo(x0 - 5, y0 - 11);
          ctx.lineTo(x0 + 5, y0 - 11);
        } else ctx.arc(x0, y0, 4, 0, Math.PI * 2);
        ctx.fill();
        if (e.text) {
          ctx.font = "11px system-ui, sans-serif";
          ctx.fillText(e.text, x0 + 7, up ? y0 + 20 : down ? y0 - 14 : y0 - 6);
        }
        return;
      }
      case "label":
        if (x0 === null || y0 === null || !e.text) return;
        ctx.font = "12px system-ui, sans-serif";
        ctx.fillText(e.text, x0, y0);
    }
  }

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }
}
