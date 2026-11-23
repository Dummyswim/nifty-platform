# Kite Connect v3: verified facts (C07)
Base `https://kite.trade/docs/connect/v3`; tags `verified(<page>, <date>)` name the page under it. Unverified = not on the pages or only assumed. API host `https://api.kite.trade`.

## Login and token
- Login URL `https://kite.zerodha.com/connect/login?v=3&api_key=<key>`; optional `redirect_params` (URL-encoded) is echoed to the redirect. verified(/user/, 2026-11-23)
- Success redirects to the registered URL with `request_token`; `status`/`action`/`type` params are not documented (we require `request_token`, ignore the rest). verified(/user/, 2026-11-23)
- Exchange: `POST /session/token`, form `api_key, request_token, checksum`, `checksum = sha256(api_key + request_token + api_secret)` (hex). verified(/user/, 2026-11-23)
- `request_token` lives only a few minutes: exchange immediately. verified(/user/, 2026-11-23)
- Session `data` carries `user_id, access_token, public_token, enctoken, refresh_token, login_time, ...`; we keep only `access_token` and `user_id`. verified(/user/, 2026-11-23)
- Headers `Authorization: token <api_key>:<access_token>` and `X-Kite-Version: 3`. verified(/user/, 2026-11-23)
- The access token expires at 06:00 IST the next day (regulatory), or on logout / master logout. verified(/user/, 2026-11-23)
- `GET /user/profile` returns `user_id, user_name, email, broker, exchanges, products, ...` and no tokens. verified(/user/, 2026-11-23)
- Logout is `DELETE /session/token?api_key&access_token` (we do not call it). verified(/user/, 2026-11-23)

## Envelope and errors
- Params: GET/DELETE query string; POST/PUT `application/x-www-form-urlencoded`. verified(/response-structure/, 2026-11-23)
- Success `{"status":"success","data":...}`; failure 4xx/5xx `{"status":"error","message":...,"error_type":...}`. verified(/response-structure/, 2026-11-23)
- Datetime strings `yyyy-mm-dd hh:mm:ss` in IST (page says "UTC+5.5"); dates `yyyy-mm-dd`. verified(/response-structure/, 2026-11-23)
- `error_type`: TokenException (preceded by 403; session ended), UserException, OrderException, InputException, MarginException, HoldingException, NetworkException (API cannot reach OMS), DataException, GeneralException; PermissionException is not listed. verified(/exceptions/, 2026-11-23)
- HTTP codes: 400 bad params, 403 session expired, 404, 405, 410, 429 rate limited, 500, 502 OMS down, 503 API down, 504 gateway timeout. verified(/exceptions/, 2026-11-23)
- Our mapping: TokenException/403 -> AUTH_EXPIRED; 429 -> RATE_LIMITED; PermissionException or a plan/entitlement message -> ENTITLEMENT; 5xx/Network/timeouts -> NETWORK; InputException/DataException/unparsable body -> BAD_DATA. unverified (the page gives no per-type status)
- No `Retry-After` or backoff guidance for 429 is documented. verified(/exceptions/, 2026-11-23)

## Rate limits
- Quote endpoints 1 req/s; historical candles 3 req/s; all other endpoints 10 req/s. verified(/exceptions/, 2026-11-23)
- Spec/05 expected ~10 req/s for non-historical calls: `/quote` is 1 req/s (spec updated), the instrument dump is "once a day". verified(/market-quotes/, 2026-11-23)

## Historical candles
- `GET /instruments/historical/:instrument_token/:interval?from&to[&continuous][&oi]`, `from/to` as `yyyy-mm-dd hh:mm:ss`. verified(/historical/, 2026-11-23)
- Intervals: `minute 3minute 5minute 10minute 15minute 30minute 60minute day`. verified(/historical/, 2026-11-23)
- Candle `[ "2017-12-15T09:15:00+0530", o, h, l, c, volume ]`, a 7th element `oi` only with `oi=1`; the offset has no colon. verified(/historical/, 2026-11-23)
- Maximum days per request per interval is NOT on the page. Live probe: a minute range of 61 days was accepted (kite-smoke, 2026-11-23), so the 60-day working limit is conservative; the true maximum is not found. Other intervals still assumed (3/5/10m 100, 15/30m 200, 60m 400, day 2000). verified(live kite-smoke, 2026-11-23)
- `continuous=1` works for NFO/MCX futures day candles through a live contract token; expired options are not retrievable ("unless you regularly download and cache them"). verified(/historical/, 2026-11-23)
- `/instruments` lists live contracts only, so expired-option history is absent (D12 holds). verified(/historical/, 2026-11-23)
- Historical works on this account (375 NIFTY 50 1m candles for 2026-11-23); WebSocket entitlement is checked in C08. verified(live kite-smoke, 2026-11-23)

## Instruments and quotes
- `GET /instruments` and `GET /instruments/:exchange` return a gzipped CSV dump, generated once a day (request about 08:30 IST). verified(/market-quotes/, 2026-11-23)
- Columns in order: `instrument_token, exchange_token, tradingsymbol, name, last_price, expiry, strike, tick_size, lot_size, instrument_type, segment, exchange`. verified(/market-quotes/, 2026-11-23)
- `instrument_type` EQ, FUT, CE, PE; segments like NFO-FUT, NFO-OPT. Use exchange + tradingsymbol as the key, not the token. verified(/market-quotes/, 2026-11-23)
- The NIFTY 50 index row (segment INDICES, NSE) is in the live dump (4541 NIFTY-related rows kept). verified(live kite-smoke, 2026-11-23)
- `/quote` up to 500 instruments, `/quote/ohlc` and `/quote/ltp` up to 1000; query `i=NSE:NIFTY+50` repeated; missing keys are absent. verified(/market-quotes/, 2026-11-23)
- `/quote` fields: `instrument_token, timestamp, last_trade_time, last_price, volume, oi, ohlc, depth{buy,sell}[price,quantity,orders]`. verified(/market-quotes/, 2026-11-23)

## WebSocket (parser lands in C08)
- `wss://ws.kite.trade?api_key=<key>&access_token=<token>`. verified(/websocket/, 2026-11-23)
- Messages `{"a":"subscribe","v":[tokens]}`, `{"a":"unsubscribe","v":[tokens]}`, `{"a":"mode","v":["full",[tokens]]}`; modes `ltp` (8 B), `quote` (44 B), `full` (184 B). verified(/websocket/, 2026-11-23)
- Frame: int16 packet count, then per packet an int16 length and the packet; 1-byte heartbeats. Endianness is not stated (we assume big-endian). verified(/websocket/, 2026-11-23)
- Tradable packet int32 offsets: 0 token, 4 ltp, 8 last qty, 12 avg price, 16 volume, 20 buy qty, 24 sell qty, 28 o, 32 h, 36 l, 40 c (quote ends), 44 last trade time, 48 oi, 52 oi high, 56 oi low, 60 exchange time, 64-184 depth (5 bid + 5 ask, 12 B each: qty int32, price int32, orders int16, 2 pad). verified(/websocket/, 2026-11-23)
- Index packet: 0 token, 4 ltp, 8 high, 12 low, 16 open, 20 close, 24 change (quote ends, 28 B), 28 exchange time (32 B); no volume/OI/depth. verified(/websocket/, 2026-11-23)
- Prices in paise: divide by 100; currency segments by 10000000. verified(/websocket/, 2026-11-23)
- Limits: 3000 instruments per connection, 3 connections per API key. verified(/websocket/, 2026-11-23)
- Text messages (JSON): `order` (postback), `error`, `message`; market data is always binary. verified(/websocket/, 2026-11-23)
- Segment from the token's low byte, reconnect guidance and exact error strings are not documented. unverified
