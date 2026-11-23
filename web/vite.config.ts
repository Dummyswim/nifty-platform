declare const process: { env: Record<string, string | undefined> }; // no @types/node dependency
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/ws": { target: "ws://127.0.0.1:8000", ws: true },
    },
  },
  build: { chunkSizeWarningLimit: 700 }, // the lazy ECharts chunk is ~520 kB
  preview: {
    host: "127.0.0.1",
    proxy: {
      "/api": `http://127.0.0.1:${process.env.E2E_API_PORT ?? "8000"}`,
      "/ws": { target: `ws://127.0.0.1:${process.env.E2E_API_PORT ?? "8000"}`, ws: true },
    },
  },
  test: { environment: "node", exclude: ["e2e/**", "node_modules/**", "dist/**"] },
});
