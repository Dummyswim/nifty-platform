# Multi-pane chart — design

Branch `feature/sensex-multiview` (worktree `nifty-platform-dev`, DB `nifty_dev`, ports 8001/8081).
First of three pieces of work: panes → Sensex (index + options) → UI refresh.

## Intent
During a live session the user watches the NIFTY index and an ATM call and put at the same time, the
way they do in TradingView with a split layout. Today the Chart page shows one instrument. The goal is
1, 2 or 3 chart panes in one window, each showing any index or recorded option contract, with
free-hand resizing.

## Goals
- Layouts: **1 pane** (default), **2 panes `[A|B]`** side by side, **3 panes** = big pane left, two
  stacked on the right. Switchable from the chart toolbar.
- Each pane has its own instrument and timeframe.
- Dividers are draggable (free resize); sizes are remembered.
- Option panes show what the live collector recorded (ticks → 1m bars); nothing is synthesised.
- Crosshair follows time across panes.
- Layout, per-pane instrument/timeframe and divider sizes survive a reload.

## Non-goals (this piece)
- Sensex (next piece). Historical option candles from Kite (later; user chose "recorded live" first).
- Visual restyle (third piece). More than 3 panes, stacked top/bottom 2-pane, free grid layouts.
- Schema changes: none. One small backend fix (found while planning): engine-run job keys ignore the
  data, so a resubmit after new bars returned the stale run. The key now includes the symbol's latest
  bar time (`data_until`). Needed for live option-pane indicators; also fixes stale History-mode
  indicators after a backfill.

## Anti-goals (fail even if it "works")
- The single-pane chart behaves differently from today (indicators, replay, live, drawings,
  "Open on chart" from Backtests/Research).
- Any change to engine/indicator computation or to stored data.
- Merging to `main` before the user has tried it on 8081 and said so.

## Constraints (found in the code)
- `GET /bars?symbol=` and the WS `subscribe` both resolve an exact `instrument_id`, and the Options page
  already renders a contract with `ChartView` (`web/src/options/Options.tsx:36`). Option panes need no
  backend change.
- `GET /instruments` hides CE/PE contracts; option choice uses the existing
  `GET /options/expiries` and `GET /options/chain` (rows carry `recorded`).
- Chart state today is one global `symbol`/`tf` in `web/src/store.ts`, read by `pages/Chart.tsx` and set
  by Backtests' audit drawer and Research's "Open on chart".
- Indicator on/off and params are one global pref (`prefs.indicators`, `useIndicators.ts`).
- No new dependencies (AGENTS.md: smallest diff, no unlisted deps).

## Approaches considered
- **A. Pane component + hand-written dividers (chosen by the user).** Extract today's chart body into a
  `ChartPane` with its own symbol/tf, render 1–3 in a split container with ~60 lines of divider code.
  No dependency; computations reused as they are.
- B. Same with `react-resizable-panels`: more polish (keyboard resize, persistence) but a new dependency.
- C. lightweight-charts' built-in panes: rejected, they only stack vertically on one time axis, so
  `[A|B]` is impossible.

## Design (decided)
**Active pane, one toolbar (the TradingView model).** The existing toolbar stays where it is and acts on
the *active* pane: symbol, timeframe, drawing tool, Indicators sidebar. Clicking inside a pane makes it
active (accent border). In 1-pane layout this is exactly today's page.

**Shared across panes:** History/Live mode, replay cursor (all panes step together), crosshair time.

**Layout switch:** a small segmented control in the toolbar: `1 · 2 · 3`. Going from 3 to 2 keeps panes
A and B; going up adds panes that start on the active pane's instrument and timeframe.

```
1:  [            A            ]
2:  [     A      |     B      ]
3:  [     A      |     B      ]
    [            |------------]
    [            |     C      ]
```

**Dividers:** vertical divider between left and right; in layout 3 a horizontal divider between B and C.
Pointer drag, min 15 % per pane, double-click resets to equal. Charts resize live while dragging.

**Choosing an option contract:** the symbol select lists the index instruments as today plus an
"Option…" entry that opens a small picker: underlying (NIFTY for now) → expiry → strike (ATM marked) →
CE/PE. Contracts not recorded are shown but marked "not recorded"; choosing one opens an empty pane with
that note. The pane title shows the contract (e.g. `NIFTY 26DEC 25800 CE · 1m`).

**Indicators (user decision: on every pane, index and option, same indicators).** Settings stay global as
today; every pane runs the enabled engines on its own instrument and timeframe.
- History mode: unchanged path (`engine_run` job on the pane's stored 1m bars, `worker/handlers.py:21`).
  Recorded option bars are stored like index bars, so this works for contracts with no backend change.
- Live mode, index pane: the collector's live run, as today.
- Live mode, option pane: the collector runs no engines for options (`collector/kite_run.py:127`), and
  running them for every recorded contract × timeframe would be heavy. Instead the pane uses the History
  path and re-runs it when its stream delivers a finalized bar (`wake`). Small: a contract has a few
  hundred recorded 1m bars per day. Provisional (forming-bar) indicator values are index-only.
- Options carry real traded volume (the index has none: it uses the futures proxy live and TWAP in
  history). Engines already honour `volume_kind`, so on option panes VWAP / flow use real volume
  automatically. Other option data worth using later is in `docs/TODO.md`.
- An option with too few recorded bars for an engine's warm-up shows the engine's normal warm-up state.

**Engine cards and Indicators sidebar** show the active pane's engines.

**Live:** each pane opens its own WS subscription for its instrument/tf (≤ 3 sockets). The banner shows the
collector state once. Verified in `collector/service.py:155-196`: option feeds publish finalized bars
(`wake`) and forming bars (`provisional`) on `live:<instrument_id>` like the index, so option panes
update live with no backend change. Known limitation, left as is: the provisional-bar throttle (250 ms)
is shared by all instruments, so an option's forming candle may refresh less smoothly than the index's;
finalized bars are unaffected.

**Replay bar** uses the active pane's bar times.

**Persistence:** new pref `chart_layout` = `{layout: 1|2|3, active, panes:[{symbol, tf}], sizes}`.
The old `chart` pref (`{symbol, tf}`) is still read on first load and keeps being written for pane A, so
switching back to `main` stays consistent.

**"Open on chart" from Backtests/Research** targets the active pane (its symbol/tf/focus), as today.

## Left to the builder
- Component split inside `pages/Chart.tsx` (e.g. `ChartPane`, `SplitLayout`, `OptionPicker`) and how
  per-pane state lives in the store (array of panes + active index).
- Crosshair sync mechanics (lightweight-charts `subscribeCrosshairMove` / `setCrosshairPosition`).
- Tests: vitest for layout/pref logic and divider maths; one Playwright smoke (switch to 3 panes, pick a
  contract, resize). `make check` and `make e2e` green; manual check on 8081.
