# Execution (module `nifty.execution`)

Signal on closed bar t ⇒ order fills at open of t+1 (D06). Never fill at the signal bar's close unless a rule below says so.

## Modes
| | `tv` (Pine ports; mirrors TradingView; verify vs golden) | `conservative` (research default) |
|---|---|---|
| entry | market at next bar open | next bar open; stop/target anchored to the actual entry price |
| intrabar path | O→H→L→C if `(high−open) < (open−low)`, else O→L→H→C; tie ⇒ log as uncertain | none: both barriers inside one bar ⇒ `STOP` + flag `ambiguous_bar` |
| stop fill | at the stop; if the bar opens through it, at the open | same (at the open, worse) |
| target fill | at the limit; if the bar opens beyond it, at the open | at the target (no gap improvement) |
| exit on entry bar | allowed | allowed |
| time exit | script-defined | close of the last allowed bar; `max_hold_bars` counts from the entry bar inclusive |
| costs | commission % per side from `strategy()` | explicit `cost_pts` per round trip; every report shows it |

## BrokerEmulator (`tv` mode; used by NVS)
- Orders: market `entry`, `close`, `close_all`; bracket `exit` (stop and/or limit, OCO).
- `close()` fills at the next open. `close(immediately=True)` and `close_all(immediately=True)` fill at the current close.
- A bracket resolves by the first level reached along the assumed path.
- A position closed by the emulator before the script runs on bar t is visible to the script at t; one closed via `immediately` is visible at t+1.
- No pyramiding, margin model or bar magnifier. Fixed `qty`. Commission = percent of fill value per side.
- NVS `costBps` R-math is script math inside the engine, separate from emulator commission.

## `resolve_barriers` (pure, shared by research and bracket logic)
`resolve_barriers(side, entry_px, stop_px, target_px, bars, max_hold_bars, mode) -> Resolution(exit_idx, exit_px, reason, flags, mae_pts, mfe_pts, bars_held)`.
`bars[0]` is the entry bar (entry at its open). `reason` ∈ `TARGET|STOP|TIME`; research maps these to `TARGET_FIRST|STOP_FIRST|TIME_EXIT`. MAE/MFE on the exit bar are clipped at the exit price.
Tests on hand-built bars: gap through stop, gap through target, same-bar both, timeout, entry-bar exit.
Fixture (research §3): bar 2026-11-18 09:30 O 25293.95 H 25318.05 L 25289.40 C 25314.55; bearish entry at the open, target 25273.95, stop 25305.95 ⇒ `STOP` (high ≥ stop; low > target; no ambiguity).

NVS-specific exit timing (non-EOD reasons exit at the next open) lives in the NVS port, not here.
