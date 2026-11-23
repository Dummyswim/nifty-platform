import { defineConfig } from "@playwright/test";

// Run through `make e2e` (tools/e2e_run.py starts the API and the built SPA and sets the env).
export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  reporter: "line",
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE ?? "http://127.0.0.1:8080",
    viewport: { width: 1280, height: 800 },
    browserName: "chromium",
  },
});
