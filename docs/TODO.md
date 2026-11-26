# TODO / ideas to revisit

## Option data the indicators could use (from the multi-pane work, 2026-11-25)
Options carry data the NIFTY index does not. Each item needs its own design before use.
- **Real volume:** used automatically on option panes (engines honour `volume_kind`). Revisit whether the
  index engines should take volume from the ATM options instead of the front-month future proxy.
- **Open interest (OI):** stored per tick (`ticks.oi`) and served by `/options/contract-bars` (`oi`).
  Ideas: OI change vs price (long build-up / short covering), OI overlay pane under option charts,
  call-vs-put OI shift around ATM as a flow signal for the index.
- **Bid/ask and depth quantities:** stored per tick (`bid, ask, bid_qty, ask_qty`). Ideas: spread as a
  liquidity filter for signals, bid/ask quantity imbalance as an order-flow proxy (the index has none).
- **Implied volatility / Greeks:** computed in `nifty.options.bs` (needs `options.r` set). Ideas: IV
  regime as a filter, IV crush around events, delta-adjusted option signals.
- **Put/call relationships:** CE vs PE premium divergence at the same strike as a confirmation of index
  direction.

## Known limitations
- Collector provisional-bar throttle (250 ms) is shared by all instruments, so option forming candles may
  refresh less smoothly than the index (`collector/service.py:166`).
- Option panes show only collector-recorded data; historical option candles from Kite are a later step.
