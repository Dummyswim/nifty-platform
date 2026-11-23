import { useEffect, useRef, useState } from "react";
import { type CollectorState, type LiveBars, type ServerMsg, backoffMs, oneBar } from "./messages";

export interface LiveState {
  socket: "connecting" | "open" | "closed";
  state: CollectorState | null;
  detail: string;
  /** latest bars message (finalized or provisional); `seq` changes on every delivery */
  bars: { seq: number; data: LiveBars; provisional: boolean } | null;
  /** bumps when engine outputs changed (event / panel): refetch plots, events, overlays */
  version: number;
}

const wsUrl = () => `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/v1/stream`;

/** WebSocket client: snapshot first, reconnect with backoff, resubscribe with the last cursor. */
export function useLiveStream(opts: { instrument: string; timeframe: string; engines: string[]; enabled: boolean }): LiveState {
  const [st, setSt] = useState<LiveState>({ socket: "connecting", state: null, detail: "", bars: null, version: 0 });
  const engines = opts.engines.join(",");

  useEffect(() => {
    if (!opts.enabled) return;
    let alive = true;
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let cursor: number | null = null;
    let seq = 0;
    setSt({ socket: "connecting", state: null, detail: "", bars: null, version: 0 });

    const connect = () => {
      ws = new WebSocket(wsUrl());
      ws.onopen = () => {
        attempt = 0;
        setSt((s) => ({ ...s, socket: "open" }));
        ws!.send(JSON.stringify({ op: "subscribe", instrument: opts.instrument, timeframe: opts.timeframe, engines: engines ? engines.split(",") : [], ...(cursor !== null ? { cursor } : {}) }));
      };
      ws.onmessage = (ev) => {
        const m = JSON.parse(String(ev.data)) as ServerMsg;
        if (m.type === "snapshot") {
          cursor = m.cursor ?? cursor;
          setSt((s) => ({ ...s, bars: { seq: ++seq, data: m.bars, provisional: false } }));
        } else if (m.type === "bar") {
          if ("bars" in m && m.bars) {
            cursor = Math.max(cursor ?? 0, ...m.bars.t);
            setSt((s) => ({ ...s, bars: { seq: ++seq, data: m.bars, provisional: false } }));
          } else if ("bar" in m && opts.timeframe === "1m") {
            setSt((s) => ({ ...s, bars: { seq: ++seq, data: oneBar(m.bar), provisional: true } }));
          }
        } else if (m.type === "event" || m.type === "panel") {
          setSt((s) => ({ ...s, version: s.version + 1 }));
        } else if (m.type === "status") {
          setSt((s) => ({ ...s, state: m.state, detail: m.detail ?? "" }));
        }
      };
      ws.onclose = () => {
        if (!alive) return;
        setSt((s) => ({ ...s, socket: "closed" }));
        timer = setTimeout(connect, backoffMs(attempt++));
      };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => {
      alive = false;
      clearTimeout(timer);
      ws?.close();
    };
  }, [opts.instrument, opts.timeframe, engines, opts.enabled]); // eslint-disable-line react-hooks/exhaustive-deps

  return st;
}
