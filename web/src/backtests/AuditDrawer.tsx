import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { AuditOut, BacktestOut, InstrumentOut } from "../api/schemas";
import type { Tf } from "../chart/geometry";
import { TF_SEC } from "../replay/logic";
import { useReplay } from "../replay/store";
import { useUi } from "../store";
import { auditOverlays } from "./audit";

const sec = (iso: string) => Math.floor(Date.parse(iso) / 1000);

export function AuditDrawer({ bt, tradeId, onClose }: { bt: BacktestOut; tradeId: string; onClose: () => void }) {
  const set = useUi((s) => s.set);
  const audit = useQuery({
    queryKey: ["audit", bt.backtest_id, tradeId],
    queryFn: () => api<AuditOut>(`/backtests/${bt.backtest_id}/audit/${encodeURIComponent(tradeId)}?window=10`),
  });
  const instruments = useQuery({ queryKey: ["instruments"], queryFn: () => api<InstrumentOut[]>("/instruments") });
  const a = audit.data;
  const tf = bt.timeframe as Tf;
  const symbol = instruments.data?.find((i) => i.instrument_id === bt.instrument_id)?.tradingsymbol;

  const open = (replay: boolean) => {
    if (!a) return;
    const from = sec(a.trade.signal_bar_start ?? a.trade.entry_time);
    set({
      page: "chart", tf, ...(symbol ? { symbol } : {}),
      focus: { from, to: sec(a.trade.exit_time), nonce: Date.now(), tf, extra: auditOverlays(a) },
    });
    useReplay.setState({ cursor: replay ? from + TF_SEC[tf] : null, playing: false });
  };

  return (
    <aside className="drawer" role="dialog" aria-label="Trade audit" data-testid="audit">
      <header>
        <h3>Trade audit</h3>
        <button className="ghost" onClick={onClose} aria-label="Close">✕</button>
      </header>
      {audit.isLoading && <p className="muted">Loading…</p>}
      {audit.isError && <p role="alert" className="error">{(audit.error as Error).message}</p>}
      {a && (
        <>
          <dl>
            <dt>Side</dt><dd>{a.trade.side}</dd>
            <dt>Entry</dt><dd>{new Date(a.trade.entry_time).toLocaleString("en-GB", { timeZone: "Asia/Kolkata" })} @ {a.trade.entry_px.toFixed(2)}</dd>
            <dt>Exit</dt><dd>{new Date(a.trade.exit_time).toLocaleString("en-GB", { timeZone: "Asia/Kolkata" })} @ {a.trade.exit_px.toFixed(2)}</dd>
            <dt>Stop / Target</dt><dd>{a.levels.stop_px_pts?.toFixed(2) ?? "n/a"} / {a.levels.target_px_pts?.toFixed(2) ?? "n/a"}</dd>
            <dt>Exit reason</dt><dd>{a.exit_reason} {a.stop_hit ? "· stop hit" : a.target_hit ? "· target hit" : ""}</dd>
            <dt>P&L</dt><dd>{a.pnl_pts.toFixed(2)} pts{a.pnl_inr !== null && a.pnl_inr !== undefined ? ` · ₹${a.pnl_inr.toFixed(2)}` : ""}{a.roi_pct !== null && a.roi_pct !== undefined ? ` · ${a.roi_pct.toFixed(1)}%` : ""}</dd>
            <dt>Strike / type</dt><dd>{a.strike ?? "n/a (index trade)"} / {a.option_type ?? "n/a"}</dd>
            <dt>Bars held</dt><dd>{a.trade.bars_held}</dd>
          </dl>
          <p className="muted small">{a.window_bars.length} bars and {a.events.length} events around the trade.</p>
          <div className="row gap">
            <button onClick={() => open(false)} data-testid="open-chart">Open on chart</button>
            <button onClick={() => open(true)}>Replay from here</button>
          </div>
        </>
      )}
    </aside>
  );
}
