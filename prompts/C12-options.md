# C12 · Options dashboard + CE/PE paper mapping
effort: med · deps: C06, C08 · reads: `docs/spec/00-decisions.md` D10–D12 · `docs/spec/07-research.md` §Index vs option · `docs/spec/01-contracts.md` (units, TradeRecord) · `docs/spec/08-kite-verified.md` · webapp prompt L153–194 (view_range)
pine: — · tools: bash (`make test`, `make e2e`) · browser canvas · create/edit
**If short:** 1 chain math + API · 2 option recording · 3 Options page · 4 paper mapping.

**Goal.** The Options panel (strike type, CE/PE, expiry, dynamic strike loading, chart + volume + OI + Greeks) and an honest CE/PE paper mapping on recorded data only.

**Do**
1. `nifty.options` (pure, no I/O):
   - `strike_step` from the instrument master (modal gap of the listed strikes for that expiry; never hard-coded). `atm(spot, strikes)` = nearest listed strike (tie ⇒ lower, log it).
   - Strike types as offsets in steps, editable prefs: Deep ITM 5 · ITM 2 · ATM 0 · OTM 2 · Deep OTM 5 (CE: ITM = lower strikes; PE mirrored). Defaults are ours; log in STATE.
   - Expiry kinds from the master: current weekly, next weekly, monthly. An expiry the master does not list ⇒ `unavailable`, never guessed.
   - Black-Scholes price, delta, gamma, theta, vega and implied vol (bisection); q = 0 labelled; T = time to 15:30 IST of the expiry; `r` is a pref with **no invented default** ⇒ Greeks `n/a` until set; values labelled `computed` (D11). Known values S=K=100, T=1, r=0.05, σ=0.2: call 10.4506, put 5.5735, call delta 0.6368.
2. Recording: extend the C08 collector to subscribe a window (ATM ± `window_steps`, default 5, pref; CE and PE; chosen expiries; `full` mode for bid/ask/OI), re-centre when spot moves ≥1 step, ≤3,000 instruments; build option 1m bars from ticks (OHLC of ltp, volume delta, last OI). Never synthesise option prices from index candles (D12). Expose per-contract recording coverage.
3. API: `options/expiries?underlying=NIFTY` · `options/chain?expiry` (strikes, ATM flag, CE/PE last quote with age, OI, IV/Greeks or `n/a`) · `options/contract-bars?contract_id&tf&from&to` (volume and OI series, coverage flags). Then `make api-types`.
4. Options page per webapp L153–194: strike type, option type, expiry; reads spot; shows ATM and neighbours; selecting a strike opens its chart (reuse `ChartView`) with volume and OI panes and Greeks if available. Honest empty states: "not recorded", "no quote", "Greeks n/a: set r in Settings".
5. `nifty.options.paper`: maps an index trade to a contract by strike type + expiry policy **chosen at entry time**. Entry at the recorded ask of the last tick ≤ entry time; exit at the recorded bid ≤ exit time; max staleness 60 s (pref) else `no_quote` ⇒ the trade is skipped and counted. Only recorded contracts (D12). `synthetic=true` when the exit was index-triggered. `pnl_inr = (exit_prem − entry_prem) × lots × lot_size − cost_inr` with explicit `cost_inr` (default 0, shown). Units never mixed (`UnitMismatch` test). Backtest option `option_policy`; the Backtests page shows index (pts) and option (INR) columns plus the `no_quote` count.
6. Tests: BS known answers, put–call parity, IV round trip · ATM tie · strike types for CE and PE · expiry derivation from a fixture master (weekly, monthly, missing) · window re-centring · paper mapping (stale ⇒ skip, ask/bid used, synthetic flag, lot arithmetic) · API contract tests on a seeded `nifty_test`. Fixtures: a tiny hand-made option set in `fixtures/options_demo/`, labelled SYNTHETIC, used by tests and e2e only, never loaded into the dev database.

**Acceptance.** `make check` and `make e2e` green (add an Options smoke on the synthetic fixture: pick strike type and expiry, see ATM, open a contract chart). In the browser canvas on the dev DB the page shows honest empty states, not errors.
**Record in STATE:** pref keys and defaults, API shapes, staleness rule, `no_quote` handling, fixture path.
