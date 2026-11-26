import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import type { ChainOut, ChainSide, ExpiriesOut } from "../api/schemas";
import { contractLabel } from "./optionPane";

/** Pick an option contract for a chart pane: expiry -> strike (ATM marked) -> CE / PE. */
export function OptionPicker({ onPick, onClose }: { onPick: (contractId: string, label: string) => void; onClose: () => void }) {
  const exps = useQuery({ queryKey: ["opt-expiries"], queryFn: () => api<ExpiriesOut>("/options/expiries") });
  const kindOf = (d: string) => Object.entries(exps.data?.kinds ?? {}).find(([, v]) => v === d)?.[0];
  const [picked, setPicked] = useState<string | null>(null);
  const expiry = picked ?? exps.data?.kinds["current weekly"] ?? exps.data?.expiries[0] ?? null;
  const chain = useQuery({
    queryKey: ["opt-chain-picker", expiry],
    queryFn: () => api<ChainOut>(`/options/chain?expiry=${expiry}&width=10`),
    enabled: !!expiry,
  });
  const c = chain.data;
  const side = (s: ChainSide | null | undefined, strike: number, type: "CE" | "PE") =>
    s ? (
      <button className={s.recorded ? "" : "unrecorded"} data-testid={`pick-${type}`} data-recorded={s.recorded}
        title={s.recorded ? s.contract_id : `${s.contract_id}: not recorded`}
        onClick={() => onPick(s.contract_id, contractLabel(c!.underlying, c!.expiry, strike, type))}>
        {type}{s.recorded ? "" : " ·"}
      </button>
    ) : <span className="muted">—</span>;

  return (
    <div className="picker-backdrop" onClick={onClose}>
      <div className="picker" role="dialog" aria-label="Choose option contract" data-testid="option-picker" onClick={(e) => e.stopPropagation()}>
        <header>
          <b>Option contract</b>
          <button className="ghost" onClick={onClose} aria-label="Close">✕</button>
        </header>
        {exps.isSuccess && !exps.data.expiries.length && <p className="muted">No option contracts are stored. Settings → Connect Kite → Refresh instruments.</p>}
        {!!exps.data?.expiries.length && (
          <label>Expiry{" "}
            <select value={expiry ?? ""} onChange={(e) => setPicked(e.target.value)} aria-label="Expiry">
              {exps.data.expiries.map((d) => <option key={d} value={d}>{d}{kindOf(d) ? ` (${kindOf(d)})` : ""}</option>)}
            </select>
          </label>
        )}
        {c && (
          <>
            <p className="muted">Spot {c.spot ?? "n/a"} · ATM {c.atm ?? "n/a"} · “·” = not recorded (shows an empty chart)</p>
            <div className="picker-rows">
              {c.rows.map((r) => (
                <div key={r.strike} className={`picker-row ${r.atm ? "atm" : ""}`} data-strike={r.strike}>
                  {side(r.ce, r.strike, "CE")}
                  <span className="strike">{r.strike}{r.atm ? " ATM" : ""}</span>
                  {side(r.pe, r.strike, "PE")}
                </div>
              ))}
            </div>
          </>
        )}
        {expiry && chain.isLoading && <p className="muted">Loading chain…</p>}
      </div>
    </div>
  );
}
