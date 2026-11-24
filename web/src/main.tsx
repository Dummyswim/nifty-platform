import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { Login } from "./pages/Login";
import { Settings } from "./pages/Settings";
import { type Page, useUi } from "./store";
import "./styles.css";

const Chart = lazy(() => import("./pages/Chart").then((m) => ({ default: m.Chart })));
const Backtests = lazy(() => import("./backtests/Backtests").then((m) => ({ default: m.Backtests })));
const Research = lazy(() => import("./research/Research"));
const Options = lazy(() => import("./options/Options"));
const Analytics = lazy(() => import("./backtests/Analytics"));
const qc = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } });

// Kite redirects back to /settings?kite=connected|error
if (new URLSearchParams(window.location.search).has("kite")) useUi.setState({ page: "settings" });

function Shell({ onLogout }: { onLogout: () => void }) {
  const { page, set } = useUi();
  const tab = (id: Page, label: string) => (
    <button className={page === id ? "on" : ""} aria-current={page === id ? "page" : undefined} onClick={() => set({ page: id })}>
      {label}
    </button>
  );
  return (
    <div className="shell">
      <header>
        <span className="brand">NIFTY</span>
        <nav>
          {tab("chart", "Chart")}
          {tab("backtests", "Backtests")}
          {tab("research", "Research")}
          {tab("analytics", "Analytics")}
          {tab("options", "Options")}
          {tab("settings", "Settings")}
        </nav>
        <button className="ghost" onClick={onLogout}>
          Sign out
        </button>
      </header>
      <Suspense fallback={<p className="muted pad">Loading chart…</p>}>
        {page === "chart" ? <Chart /> : page === "backtests" ? <Backtests /> : page === "research" ? <Research /> : page === "analytics" ? <Analytics /> : page === "options" ? <Options /> : <Settings />}
      </Suspense>
    </div>
  );
}

function App() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ user_id: number }>("/auth/me") });
  if (me.isLoading) return <p className="muted pad">Loading…</p>;
  if (!me.isSuccess) return <Login onDone={() => void me.refetch()} />;
  const logout = () => void api("/auth/logout", { method: "POST", body: {} }).finally(() => { qc.clear(); window.location.reload(); });
  return <Shell onLogout={logout} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
