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
import type { DrawingKind } from "../api/schemas";
import { type Shape, type TP, timeToLogical } from "./geometry";

export interface DrawItem {
  id: string;
  kind: DrawingKind;
  points: TP[];
  text?: string;
  color?: string;
}

const DEFAULT = "#f5a623";

/** Custom series primitive drawing trendlines, horizontal lines, rectangles and text. Shapes are
 *  recomputed from (time, price) on every draw, so they follow zoom, pan and timeframe changes. */
export class DrawingsPrimitive implements ISeriesPrimitive<Time> {
  private chart: IChartApi | null = null;
  private series: ISeriesApi<SeriesType, Time> | null = null;
  private request: (() => void) | null = null;
  items: DrawItem[] = [];
  draft: DrawItem | null = null;
  selected: string | null = null;
  times: number[] = [];

  attached(p: SeriesAttachedParameter<Time>): void {
    this.chart = p.chart as IChartApi;
    this.series = p.series;
    this.request = p.requestUpdate;
  }
  detached(): void {
    this.chart = this.series = this.request = null;
  }

  set(items: DrawItem[], times: number[], selected: string | null, draft: DrawItem | null): void {
    this.items = items;
    this.times = times;
    this.selected = selected;
    this.draft = draft;
    this.request?.();
  }

  private x(t: number): number | null {
    const lg = timeToLogical(this.times, t);
    if (lg === null || !this.chart) return null;
    return this.chart.timeScale().logicalToCoordinate(lg as Logical);
  }
  private y(p: number): number | null {
    return this.series ? this.series.priceToCoordinate(p) : null;
  }

  /** Pixel shape of an item, or null while the chart cannot place it. */
  shapeOf(it: DrawItem): Shape | null {
    const p0 = it.points[0];
    if (!p0) return null;
    const y0 = this.y(p0.p);
    if (y0 === null) return null;
    if (it.kind === "hline") return { kind: "hline", y: y0 };
    const x0 = this.x(p0.t);
    if (x0 === null) return null;
    if (it.kind === "text") {
      const w = Math.max(20, (it.text ?? "Text").length * 7 + 8);
      return { kind: "text", a: { x: x0, y: y0 }, w, h: 16 };
    }
    const p1 = it.points[1];
    if (!p1) return null;
    const y1 = this.y(p1.p);
    const x1 = this.x(p1.t);
    if (y1 === null || x1 === null) return null;
    return { kind: it.kind, a: { x: x0, y: y0 }, b: { x: x1, y: y1 } };
  }

  private view: IPrimitivePaneView = {
    zOrder: () => "top",
    renderer: (): IPrimitivePaneRenderer => ({
      draw: (target) => {
        target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
          const all = this.draft ? [...this.items, this.draft] : this.items;
          for (const it of all) {
            const s = this.shapeOf(it);
            if (!s) continue;
            const sel = it.id === this.selected;
            ctx.save();
            ctx.strokeStyle = ctx.fillStyle = it.color ?? DEFAULT;
            ctx.lineWidth = sel ? 2 : 1.5;
            if (s.kind === "hline") {
              ctx.beginPath();
              ctx.moveTo(0, s.y);
              ctx.lineTo(mediaSize.width, s.y);
              ctx.stroke();
            } else if (s.kind === "trendline") {
              ctx.beginPath();
              ctx.moveTo(s.a.x, s.a.y);
              ctx.lineTo(s.b.x, s.b.y);
              ctx.stroke();
              if (sel) for (const q of [s.a, s.b]) handle(ctx, q.x, q.y);
            } else if (s.kind === "rect") {
              const x = Math.min(s.a.x, s.b.x);
              const y = Math.min(s.a.y, s.b.y);
              ctx.globalAlpha = 0.12;
              ctx.fillRect(x, y, Math.abs(s.b.x - s.a.x), Math.abs(s.b.y - s.a.y));
              ctx.globalAlpha = 1;
              ctx.strokeRect(x, y, Math.abs(s.b.x - s.a.x), Math.abs(s.b.y - s.a.y));
              if (sel) for (const q of [s.a, s.b]) handle(ctx, q.x, q.y);
            } else {
              ctx.font = "13px system-ui, sans-serif";
              ctx.fillText(it.text ?? "Text", s.a.x + 4, s.a.y - 4);
              if (sel) ctx.strokeRect(s.a.x, s.a.y - s.h, s.w, s.h);
            }
            ctx.restore();
          }
        });
      },
    }),
  };

  paneViews(): readonly IPrimitivePaneView[] {
    return [this.view];
  }
}

function handle(ctx: CanvasRenderingContext2D, x: number, y: number): void {
  ctx.save();
  ctx.fillStyle = "#0b0e14";
  ctx.beginPath();
  ctx.arc(x, y, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}
