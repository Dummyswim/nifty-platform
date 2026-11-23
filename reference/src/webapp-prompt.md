# Copilot Prompt: Build a Self-Hosted TradingView-Like NIFTY Options Analysis Platform

## Objective

Build a self-hosted web application similar to TradingView that runs entirely on Ubuntu Linux (Ubuntu 26.x) and focuses on live and historical analysis of the NIFTY index and NIFTY options.

The platform should support:

- Live market data ingestion from Zerodha Kite APIs.
- TradingView-style candlestick charting.
- Options chain visualization.
- Strategy indicator overlays.
- Backtesting and paper-trading simulation.
- Trade auditing and performance analytics.
- Historical tick-data storage.

The application should be designed as a production-quality personal trading workstation.

---

# Deployment Requirements

### Platform

- Ubuntu 26.x
- Self-hosted on local laptop or home server
- Docker Compose deployment preferred
- Architecture should allow migration to Kubernetes later

### Authentication

- Local authentication initially
- Single-user mode is acceptable
- Future support for multiple users

---

# Technology Preferences

Backend:

- Python FastAPI

OR

- Node.js + NestJS

Database:

- PostgreSQL
- TimescaleDB extension for time-series data

Cache / Streaming:

- Redis

Frontend:

- React
- Next.js
- TypeScript

Charting:

- TradingView Lightweight Charts
- Apache ECharts or Highcharts when necessary

---

# Market Data Requirements

## Data Source

Use Zerodha Kite Connect APIs.

Credentials will be supplied through environment variables.

Example:

```env
KITE_API_KEY=
KITE_API_SECRET=
KITE_ACCESS_TOKEN=
```

## Instruments

Initially support:

- NIFTY 50

Future:

- BANKNIFTY
- FINNIFTY
- MIDCPNIFTY

## Data Storage

Store all market data locally.

Persist:

- Tick data
- OHLC candles
- Option data
- Indicators
- Trades

Historical data should accumulate daily and remain available indefinitely unless manually purged.

---

# Charting Requirements

## Primary Chart

Default landing page should display:

### NIFTY 50

Candlestick chart

Default timeframe:

- 1 Minute

Supported timeframes:

- 1 Minute
- 3 Minute
- 5 Minute
- 10 Minute
- 15 Minute
- 30 Minute
- 1 Hour
- 1 Day

The chart should support:

- Zoom
- Pan
- Drawing tools
- Crosshair
- Price markers
- Strategy buy/sell signals
- Indicator overlays

Behavior should closely resemble TradingView.

---

# Options Dashboard

Create a dedicated Options Panel.

The user should be able to select:

### Strike Type

- Deep ITM
- ITM
- ATM
- OTM
- Deep OTM

### Option Type

- CALL
- PUT

### Expiry Selection

- Current weekly expiry
- Next weekly expiry
- Monthly expiry

### Dynamic Strike Loading

The application should automatically:

1. Read current NIFTY spot price.
2. Calculate ATM strike.
3. Display surrounding strikes.

When a strike is selected:

- Load its candlestick chart
- Show volume
- Show OI (Open Interest)
- Show Greeks if available

---

# Indicator Engine

Build a TradingView-like indicator framework.

Requirements:

- Enable/Disable indicators using toggle switches
- Display multiple indicators simultaneously
- Save user preferences

## Existing Indicator

Import and convert:

Nifty_VWAP_Spread_Scalper.pine

into native backend logic.

The indicator must:

- Produce identical signals
- Plot buy/sell entries
- Plot stop loss
- Plot targets

## New Indicator Framework

Create a framework where future Pine Scripts can be:

- Imported
- Translated
- Backtested

with minimal code changes.

---

# Backtesting Engine

Implement a strategy execution engine.

Support:

- Buy CE
- Buy PE
- Historical replay
- Signal evaluation
- Performance tracking

---

# Trade Audit Dashboard

Store and visualize:

- Entry Time
- Exit Time
- Strike
- Option Type
- Entry Price
- Exit Price
- PnL
- ROI
- Stop Loss Hit
- Target Hit

Include TradingView-style replay and audit capabilities.

---

# Analytics Dashboard

Metrics:

- Win Rate
- Profit Factor
- Sharpe Ratio
- Max Drawdown
- Consecutive Wins/Losses
- Total PnL

Export:

- CSV
- Excel
- JSON

---

# Real-Time Data Architecture

Zerodha WebSocket -> Data Collector -> Redis -> TimescaleDB -> API -> Web UI

---

# Deliverables

1. System architecture
2. Database schema
3. API design
4. Frontend wireframes
5. Docker Compose deployment
6. Zerodha integration
7. Pine Script conversion design
8. Backtesting engine
9. Audit dashboard
10. MVP roadmap
11. Production roadmap

---

# Success Criteria

- NIFTY loads on 1-minute chart at startup.
- VWAP strategy overlays automatically.
- Dynamic ITM/ATM/OTM option loading.
- Historical tick storage.
- Strategy replay.
- TradingView-like UX.
- Extensible architecture for future strategies and brokers.
