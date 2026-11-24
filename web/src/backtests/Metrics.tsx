import type { MetricsOut } from "../api/schemas";
import { fmtMetric } from "./series";

export function MetricCards({ m }: { m: MetricsOut }) {
  const noLoss = m.flags.includes("no_losses");
  const cards: [string, string, string?][] = [
    ["Trades", String(m.n_trades), `${m.wins}W / ${m.losses}L`],
    ["Win rate", m.win_rate === null ? "n/a" : `${(m.win_rate * 100).toFixed(1)}%`],
    ["Profit factor", fmtMetric(m.profit_factor, 2, noLoss ? "n/a (no losses)" : "n/a")],
    ["Total P&L", `${fmtMetric(m.total_pnl_pts)} pts`],
    ["Expectancy", `${fmtMetric(m.expectancy_pts)} pts`],
    ["Max drawdown", `${fmtMetric(m.max_drawdown_pts)} pts`],
    ["Max streak", `${m.max_consecutive_wins}W / ${m.max_consecutive_losses}L`],
    ["Sharpe", fmtMetric(m.sharpe), `${m.n_sessions} sessions${m.low_n ? " · LOW N (<30)" : ""}`],
  ];
  const o = m.option;
  if (o) {
    cards.push(
      ["Option P&L (paper)", `₹${o.total_pnl_inr.toFixed(0)}`, `${o.n_mapped} mapped · cost ₹${o.cost_inr}`],
      ["No quote / no contract", `${o.no_quote} / ${o.no_contract}`, "skipped, never reconstructed"],
    );
  }
  return (
    <div className="metrics" data-testid="metrics">
      {cards.map(([k, v, sub]) => (
        <div key={k} className="metric">
          <span className="muted">{k}</span>
          <b>{v}</b>
          {sub && <small className={sub.includes("LOW") ? "warn" : "muted"}>{sub}</small>}
        </div>
      ))}
    </div>
  );
}
