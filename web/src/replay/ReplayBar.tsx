import { useEffect, useState } from "react";
import type { Tf } from "../chart/geometry";
import { SPEEDS, type Speed, istToEpoch, jumpCursor, stepCursor, tickMs } from "./logic";
import { useReplay } from "./store";

export function ReplayBar({ times, tf }: { times: number[]; tf: Tf }) {
  const { cursor, playing, speed, set, exit } = useReplay();
  const [jump, setJump] = useState("");

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const { cursor: c } = useReplay.getState();
      const next = stepCursor(times, tf, c ?? stepStart(times, tf), 1);
      if (next === null) set({ cursor: null, playing: false });
      else set({ cursor: next });
    }, tickMs(speed));
    return () => clearInterval(id);
  }, [playing, speed, times, tf, set]);

  const step = (dir: 1 | -1) => set({ cursor: stepCursor(times, tf, cursor, dir), playing: false });
  const replaying = cursor !== null;
  return (
    <div className="replay" role="group" aria-label="Replay">
      {replaying && <span className="badge" data-testid="replay-badge">REPLAY</span>}
      <button onClick={() => step(-1)} aria-label="Step back" disabled={times.length === 0}>◀ Step</button>
      <button
        onClick={() => set({ playing: !playing, cursor: cursor ?? (playing ? null : stepStart(times, tf)) })}
        aria-label={playing ? "Pause" : "Play"}
        disabled={times.length === 0}
      >
        {playing ? "Pause" : "Play"}
      </button>
      <button onClick={() => step(1)} aria-label="Step forward" disabled={times.length === 0}>Step ▶</button>
      <select value={speed} onChange={(e) => set({ speed: Number(e.target.value) as Speed })} aria-label="Speed">
        {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
      </select>
      <input type="datetime-local" value={jump} onChange={(e) => setJump(e.target.value)} aria-label="Jump to (IST)" />
      <button onClick={() => jump && set({ cursor: jumpCursor(times, tf, istToEpoch(jump)), playing: false })} disabled={!jump}>Go</button>
      {replaying && <button className="ghost" onClick={exit}>Live</button>}
    </div>
  );
}

/** Replay from the last 200 bars when started from the live end. */
function stepStart(times: number[], tf: Tf): number | null {
  const i = Math.max(0, times.length - 200);
  return times.length ? jumpCursor(times, tf, times[i]!) : null;
}
