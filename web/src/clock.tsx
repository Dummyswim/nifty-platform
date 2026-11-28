import { useEffect, useState } from "react";

const parts = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Asia/Kolkata", weekday: "short", day: "2-digit", month: "short", year: "numeric",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

/** "Fri 27 Nov 2026 · 09:32:15 IST" for any instant, independent of the browser's time zone. */
export function istClock(d: Date): string {
  const p = Object.fromEntries(parts.formatToParts(d).map((x) => [x.type, x.value]));
  return `${p.weekday} ${p.day} ${p.month} ${p.year} · ${p.hour}:${p.minute}:${p.second} IST`;
}

/** Wall-clock IST in the header (real time, not the replay cursor). */
export function IstClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return <span className="clock" data-testid="ist-clock" title="India Standard Time">{istClock(now)}</span>;
}
