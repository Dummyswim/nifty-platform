import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { api } from "./api/client";
import { Chart } from "./pages/Chart";
import { Login } from "./pages/Login";

const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });

function App() {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ user_id: number }>("/auth/me") });
  if (me.isLoading) return <p>Loading…</p>;
  return me.isSuccess ? <Chart /> : <Login onDone={() => void me.refetch()} />;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
