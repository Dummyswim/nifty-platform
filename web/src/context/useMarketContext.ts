import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { ContextOut } from "../api/schemas";

/** Live polls every 15 s (server picks today); History fetches once for `date` (omitted = last session). */
export function useMarketContext(underlying: string, live: boolean, date?: string): { data?: ContextOut; error?: unknown } {
  const q = useQuery({
    queryKey: ["context", underlying, date ?? null, live],
    queryFn: () => api<ContextOut>(`/context?underlying=${encodeURIComponent(underlying)}${!live && date ? `&date=${date}` : ""}`),
    refetchInterval: live ? 15_000 : false,
  });
  return { data: q.data, error: q.error };
}
