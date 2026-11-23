import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";

export function Settings() {
  const prefs = useQuery({ queryKey: ["prefs"], queryFn: () => api<Record<string, unknown>>("/prefs") });
  return (
    <div className="panel">
      <h2>Settings</h2>
      <section>
        <h3>Kite</h3>
        <p className="muted">Connection status and “Connect Kite” arrive with the Kite integration (C07).</p>
      </section>
      <section>
        <h3>Preferences</h3>
        {prefs.isLoading ? (
          <p className="muted">Loading…</p>
        ) : (
          <pre data-testid="prefs">{JSON.stringify(prefs.data ?? {}, null, 2)}</pre>
        )}
      </section>
    </div>
  );
}
