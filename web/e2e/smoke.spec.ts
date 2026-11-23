import { expect, test } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "";
const SHOT = process.env.E2E_SHOT;

test("login, chart loads bars, TF switch, a horizontal line survives reload", async ({ page }) => {
  const problems: string[] = [];
  let loggedIn = false;
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("console", (m) => {
    // the unauthenticated /auth/me probe before login is an expected 401
    const expected401 = !loggedIn && m.text().includes("401");
    if (m.type() === "error" && !expected401) problems.push(`console: ${m.text()}`);
  });

  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  loggedIn = true;

  const chart = page.getByTestId("chart");
  await expect(chart).toHaveAttribute("data-symbol", "NIFTY 50");
  await expect(chart).toHaveAttribute("data-tf", "1m"); // default landing view
  await expect.poll(async () => Number(await chart.getAttribute("data-bars"))).toBeGreaterThan(1000);
  // NVS is on by default: its 15 entry markers draw even on the 1m chart (outputs are time-anchored)
  await expect(page.getByTestId("status-pine.nvs_scalper")).toHaveText("ready", { timeout: 45_000 });
  await expect(chart).toHaveAttribute("data-entry-markers", "15");
  await expect(page.getByTestId("engine-panel")).toContainText("VWAP");
  const nOverlays = Number(await chart.getAttribute("data-overlays"));
  expect(nOverlays).toBeGreaterThan(15);
  await expect(page.getByTestId("legend-c")).toHaveText(/^\d+\.\d\d$/);
  const bars1m = Number(await chart.getAttribute("data-bars"));

  await page.locator('button[data-tf="5m"]').click();
  await expect(chart).toHaveAttribute("data-tf", "5m");
  await expect.poll(async () => Number(await chart.getAttribute("data-bars"))).toBeGreaterThan(100);
  expect(Number(await chart.getAttribute("data-bars"))).toBeLessThan(bars1m);
  await expect(page.getByTestId("legend-c")).toHaveText(/^\d+\.\d\d$/);

  // horizontal line: pick the tool, click the chart
  await page.locator('button[data-tool="hline"]').click();
  const box = (await chart.boundingBox())!;
  const at = { x: box.x + box.width * 0.5, y: box.y + box.height * 0.4 };
  await page.mouse.click(at.x, at.y);
  await expect(chart).toHaveAttribute("data-drawings", "1");

  await page.reload();
  await expect(chart).toHaveAttribute("data-tf", "5m"); // last timeframe restored from prefs
  await expect(chart).toHaveAttribute("data-drawings", "1"); // the line is persisted
  await expect.poll(async () => Number(await chart.getAttribute("data-bars"))).toBeGreaterThan(100);

  if (SHOT) await page.screenshot({ path: SHOT });

  // select it (same pixel) and delete it
  await page.mouse.click(at.x, at.y);
  await page.keyboard.press("Delete");
  await expect(chart).toHaveAttribute("data-drawings", "0");

  // replay: jump into the data, entry markers are revealed only up to the cursor
  await page.getByLabel("Jump to (IST)").fill("2026-10-27T12:30");
  await page.getByRole("button", { name: "Go" }).click();
  await expect(page.getByTestId("replay-badge")).toBeVisible();
  const shown = Number(await chart.getAttribute("data-shown"));
  expect(shown).toBeGreaterThan(0);
  expect(shown).toBeLessThan(Number(await chart.getAttribute("data-bars")));
  await expect(chart).toHaveAttribute("data-entry-markers", "1"); // only the 10-23 entry is known yet
  await page.getByRole("button", { name: "Step forward" }).click();
  await expect(chart).toHaveAttribute("data-shown", String(shown + 1)); // one bar at a time
  await expect(chart).toHaveAttribute("data-entry-markers", "1");
  await page.getByRole("button", { name: "Exit replay" }).click();
  await expect(chart).toHaveAttribute("data-entry-markers", "15");
  await expect(page.getByTestId("replay-badge")).toHaveCount(0);

  // backtest -> trades -> audit -> open on chart
  await page.getByRole("button", { name: "Backtests", exact: true }).click();
  await page.getByTestId("run-backtest").click();
  await expect(page.getByTestId("trade-row")).toHaveCount(15, { timeout: 45_000 });
  await expect(page.getByTestId("metrics")).toContainText("LOW N");
  await page.getByTestId("trade-row").first().click();
  await expect(page.getByTestId("audit")).toContainText("Exit reason");
  await page.getByTestId("open-chart").click();
  await expect(chart).toHaveAttribute("data-tf", "5m");
  await expect(chart).toHaveAttribute("data-cursor", "");
  await expect.poll(async () => Number(await chart.getAttribute("data-overlays"))).toBeGreaterThan(nOverlays); // audit lines
  await expect.poll(async () => Number(await chart.getAttribute("data-bars"))).toBeGreaterThan(100);
  if (SHOT) await page.screenshot({ path: SHOT.replace(/\.png$/, "-audit.png") });

  // analytics page renders its charts
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(page.getByTestId("equity")).toBeVisible();
  await expect(page.getByTestId("session-hist").locator("canvas")).toHaveCount(1);

  // settings: Kite status badge (no live Kite call is made without a token)
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByTestId("kite-badge")).toHaveText(/not (configured|connected)/);

  expect(problems).toEqual([]);
});
