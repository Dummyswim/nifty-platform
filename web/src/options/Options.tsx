import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ChainOut, ChainSide, ContractBarsOut, ExpiriesOut } from "../api/schemas";
import { ChartView } from "../chart/ChartView";
import { OiChart } from "./OiChart";
import { EXPIRY_KINDS, type OptionType, STRIKE_TYPES, type StrikeType, ageText, fmt, greeksText, pickedStrike, sideState } from "./oi";

const noop = () => undefined;

function Cell({ s, onOpen, selected }: { s: ChainSide | null | undefined; onOpen: (id: string) => void; selected: boolean }) {
  if (!s) return <td className="muted" colSpan={3}>not listed</td>;
  const st = sideState(s);
  return (
    <>
      <td className={`pick ${selected ? "sel" : ""}`} onClick={() => onOpen(s.contract_id)} data-testid="open-contract" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen(s.contract_id)}>
        {s.last !== null && s.last !== undefined ? fmt(s.last) : <span className="muted">{st}</span>}
      </td>
      <td>{fmt(s.bid)} / {fmt(s.ask)}</td>
      <td>{fmt(s.oi, 0)}</td>
    </>
  );
}

function Contract({ id, side }: { id: string; side: ChainSide | null | undefined }) {
  const bars = useQuery({ queryKey: ["contract-bars", id], queryFn: () => api<ContractBarsOut>(`/options/contract-bars?contract_id=${encodeURIComponent(id)}`) });
  if (bars.isLoading) return <p className="muted">Loading…</p>;
  const cov = bars.data?.coverage as { recorded?: boolean; n_bars?: number; n_ticks?: number } | undefined;
  return (
    <section className="contract" data-testid="contract-panel">
      <h3>{id}</h3>
      {!cov?.recorded && <p className="muted" data-testid="not-recorded">Not recorded: the collector never subscribed this contract, and option prices are never reconstructed from the index.</p>}
      {cov?.recorded && !cov.n_bars && <p className="muted">Quotes recorded ({cov.n_ticks} ticks) but no 1m bars yet.</p>}
      {!!cov?.n_bars && (
        <div className="contract-chart">
          <ChartView symbol={id} tf="1m" tool="select" drawings={[]} onCreate={noop} onUpdate={noop} onDelete={noop} onToolDone={noop} />
        </div>
      )}
      {!!bars.data?.oi.t.length && <OiChart t={bars.data.oi.t} v={bars.data.oi.v} />}
      <div className="greeks" data-testid="greeks">
        <span>IV <b>{side?.iv != null ? `${(side.iv * 100).toFixed(1)}%` : "—"}</b></span>
        <span>Delta <b>{fmt(side?.delta, 3)}</b></span>
        <span>Gamma <b>{fmt(side?.gamma, 5)}</b></span>
        <span>Theta/day <b>{fmt(side?.theta_day, 2)}</b></span>
        <span>Vega/1% <b>{fmt(side?.vega_1pct, 2)}</b></span>
        <small className="muted">{greeksText(side)}</small>
      </div>
    </section>
  );
}

export default function Options() {
  const [st, setSt] = useState<StrikeType>("ATM");
  const [ot, setOt] = useState<OptionType>("CE");
  const [kind, setKind] = useState<(typeof EXPIRY_KINDS)[number]>("current weekly");
  const [open, setOpen] = useState<string | null>(null);
  const exps = useQuery({ queryKey: ["opt-expiries"], queryFn: () => api<ExpiriesOut>("/options/expiries"), refetchInterval: 15_000 });
  const expiry = exps.data?.kinds[kind] ?? null;
  const chain = useQuery({
    queryKey: ["opt-chain", expiry],
    queryFn: () => api<ChainOut>(`/options/chain?expiry=${expiry}&width=6`),
    enabled: !!expiry,
    refetchInterval: 5_000,
  });
  const c = chain.data;
  const strike = pickedStrike(c, st, ot);
  const row = c?.rows.find((r) => r.strike === strike);
  const picked = row ? (ot === "CE" ? row.ce : row.pe) : null;
  useEffect(() => setOpen(null), [expiry, st, ot]);
  const openSide = open ? c?.rows.flatMap((r) => [r.ce, r.pe]).find((s) => s?.contract_id === open) ?? null : null;

  return (
    <div className="page options" data-testid="options-page">
      <h2>Options</h2>
      <div className="row gap wrap">
        <label>Strike type <select value={st} onChange={(e) => setSt(e.target.value as StrikeType)} aria-label="Strike type">{STRIKE_TYPES.map((x) => <option key={x}>{x}</option>)}</select></label>
        <label>Option type <select value={ot} onChange={(e) => setOt(e.target.value as OptionType)} aria-label="Option type"><option value="CE">CALL</option><option value="PE">PUT</option></select></label>
        <label>Expiry <select value={kind} onChange={(e) => setKind(e.target.value as (typeof EXPIRY_KINDS)[number])} aria-label="Expiry kind">{EXPIRY_KINDS.map((x) => <option key={x}>{x}</option>)}</select></label>
        <span className="muted" data-testid="expiry-date">{expiry ?? "unavailable: the instrument master does not list it"}</span>
      </div>
      {exps.isSuccess && !exps.data.expiries.length && <p className="muted" data-testid="no-contracts">No option contracts are stored. Settings → Connect Kite → Refresh instruments.</p>}
      {c && (
        <>
          <p className="stats" data-testid="spot-line">
            Spot <b>{c.spot ? fmt(c.spot) : "n/a"}</b> <span className="muted">({ageText(c.spot_age_s)} old)</span> · ATM <b data-testid="atm-strike">{c.atm ?? "n/a"}</b> · step {c.step ?? "n/a"} ·{" "}
            selected <b>{strike ?? "not listed"}</b> {ot} · {c.r_set ? "r set" : <span className="warn">Greeks n/a: set r in Settings</span>}
          </p>
          {c.note && <p className="muted">{c.note}</p>}
          <table className="chain" data-testid="chain">
            <thead><tr><th colSpan={3}>CALL (CE)</th><th>Strike</th><th colSpan={3}>PUT (PE)</th></tr><tr><th>Last</th><th>Bid / Ask</th><th>OI</th><th /><th>Last</th><th>Bid / Ask</th><th>OI</th></tr></thead>
            <tbody>
              {c.rows.map((r) => (
                <tr key={r.strike} className={`${r.atm ? "atm" : ""} ${r.strike === strike ? "picked" : ""}`} data-testid={r.atm ? "atm-row" : undefined} data-strike={r.strike}>
                  <Cell s={r.ce} onOpen={setOpen} selected={open === r.ce?.contract_id} />
                  <th>{r.strike}{r.atm ? " ATM" : ""}</th>
                  <Cell s={r.pe} onOpen={setOpen} selected={open === r.pe?.contract_id} />
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      {expiry && !c && chain.isLoading && <p className="muted">Loading chain…</p>}
      {(open || picked) && <Contract id={open ?? picked!.contract_id} side={open ? openSide : picked} />}
      {!open && !picked && c && <p className="muted">Click a price to open that contract.</p>}
    </div>
  );
}
