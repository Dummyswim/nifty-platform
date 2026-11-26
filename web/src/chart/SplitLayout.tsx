import { type PointerEvent, type ReactNode, useRef } from "react";
import { type LayoutN, type Sizes, dragFrac } from "./layout";

const GAP = 6; // divider thickness, px

/**
 * 1 pane, 2 = [A|B], 3 = A big left with B over C on the right. Dividers drag freely (15..85 %),
 * double-click resets to equal. `onSizes(s, false)` while dragging, `(s, true)` once on release.
 */
export function SplitLayout({ layout, sizes, onSizes, children }: {
  layout: LayoutN; sizes: Sizes; onSizes: (s: Sizes, done: boolean) => void; children: ReactNode[];
}) {
  const box = useRef<HTMLDivElement>(null);
  const drag = useRef<{ axis: "col" | "row"; start: number; at: number; total: number; last: Sizes } | null>(null);

  const down = (axis: "col" | "row") => (e: PointerEvent<HTMLDivElement>) => {
    const r = box.current?.getBoundingClientRect();
    if (!r) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = {
      axis, start: sizes[axis], at: axis === "col" ? e.clientX : e.clientY,
      total: (axis === "col" ? r.width : r.height) - GAP, last: sizes,
    };
  };
  const move = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    const f = dragFrac(d.start, (d.axis === "col" ? e.clientX : e.clientY) - d.at, d.total);
    d.last = { ...sizes, [d.axis]: f };
    onSizes(d.last, false);
  };
  const up = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    drag.current = null;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    if (d) onSizes(d.last, true);
  };
  const divider = (axis: "col" | "row", style: React.CSSProperties) => (
    <div
      key={`divider-${axis}`}
      className={`pane-divider ${axis}`}
      data-testid={`divider-${axis}`}
      style={style}
      onPointerDown={down(axis)}
      onPointerMove={move}
      onPointerUp={up}
      onPointerCancel={up}
      onDoubleClick={() => onSizes({ ...sizes, [axis]: 0.5 }, true)}
    />
  );

  const fr = (f: number) => `minmax(0, ${f}fr) ${GAP}px minmax(0, ${1 - f}fr)`;
  const grid: React.CSSProperties =
    layout === 1 ? {} : { gridTemplateColumns: fr(sizes.col), ...(layout === 3 ? { gridTemplateRows: fr(sizes.row) } : {}) };
  const [a, b, c] = children;
  return (
    <div ref={box} className={`pane-split ${layout > 1 ? "multi" : ""}`} style={grid} data-testid="split" data-layout={layout}>
      <div className="pane-cell" style={{ gridColumn: 1, gridRow: layout === 3 ? "1 / 4" : 1 }}>{a}</div>
      {layout > 1 && divider("col", { gridColumn: 2, gridRow: layout === 3 ? "1 / 4" : 1 })}
      {layout > 1 && <div className="pane-cell" style={{ gridColumn: 3, gridRow: 1 }}>{b}</div>}
      {layout === 3 && divider("row", { gridColumn: 3, gridRow: 2 })}
      {layout === 3 && <div className="pane-cell" style={{ gridColumn: 3, gridRow: 3 }}>{c}</div>}
    </div>
  );
}
