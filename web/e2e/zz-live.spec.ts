import { type ChildProcess, spawn } from "node:child_process";
import { expect, test } from "@playwright/test";

const PY = process.env.E2E_PY ?? "python";
const BACKEND = process.env.E2E_BACKEND ?? ".";
const PASSWORD = process.env.E2E_PASSWORD ?? "";
const SHOT = process.env.E2E_SHOT;
const DEMO = "demo:NIFTY 50";

// Replays two oracle sessions as ticks (x2500) through the live pipeline, in the background.
const startDemo = (): ChildProcess =>
  spawn(PY, ["-m", "nifty.cli", "demo-replay", "--speed", "2500", "--from", "2026-10-26", "--max-sessions", "2"], {
    cwd: BACKEND, env: process.env, stdio: ["ignore", "inherit", "inherit"],
  });

test("live demo: bars arrive, NVS markers appear, stale after the feed stops, resume without duplicates", async ({ page }) => {
  test.setTimeout(240_000);
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  let demo = startDemo();
  try {
    await page.goto("/");
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    const chart = page.getByTestId("chart");
    await expect(chart).toHaveAttribute("data-symbol", "NIFTY 50");

    // the demo instrument only appears once it has bars
    await expect
      .poll(async () => {
        await Promise.all([page.waitForResponse((r) => r.url().includes("/api/v1/instruments")), page.reload()]);
        await page.waitForTimeout(300);
        return page.getByLabel("Symbol").locator(`option[value="${DEMO}"]`).count();
      }, { timeout: 60_000, intervals: [1500] })
      .toBe(1);
    await page.getByLabel("Symbol").selectOption(DEMO);
    await expect(chart).toHaveAttribute("data-symbol", DEMO);
    await page.locator('button[data-tf="5m"]').click();
    await page.getByTestId("mode-live").click();

    const banner = page.getByTestId("live-banner");
    await expect(banner).toHaveAttribute("data-state", "live", { timeout: 30_000 });
    const n = async () => Number(await chart.getAttribute("data-bars"));
    await expect.poll(n, { timeout: 20_000 }).toBeGreaterThan(5);
    const n1 = await n();
    await expect.poll(n, { timeout: 30_000 }).toBeGreaterThan(n1); // bars keep arriving

    // NVS signals are produced by the live runner and drawn as markers
    await expect(chart).not.toHaveAttribute("data-entry-markers", "0", { timeout: 120_000 });
    if (SHOT) await page.screenshot({ path: SHOT.replace(/\.png$/, "-live.png") });

    // the replay ends and the process idles: no ticks => the banner turns stale
    await expect(banner).toHaveAttribute("data-state", "stale", { timeout: 90_000 });
    const total = await n();

    // reload resumes from the DB + a fresh snapshot, without duplicate candles
    await page.reload();
    await page.getByTestId("mode-live").click();
    await expect.poll(n, { timeout: 20_000 }).toBe(total);
    await expect(page.getByTestId("live-banner")).toHaveAttribute("data-state", "stale", { timeout: 30_000 });

    // the feed resumes (a new replay process): the banner recovers, still no duplicates
    demo.kill("SIGTERM");
    await new Promise((r) => setTimeout(r, 1500));
    demo = startDemo();
    await expect(page.getByTestId("live-banner")).toHaveAttribute("data-state", "live", { timeout: 60_000 });
    await expect.poll(n, { timeout: 20_000 }).toBe(total);
    expect(errors).toEqual([]);
  } finally {
    demo.kill("SIGTERM");
  }
});
