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
  await expect(page.getByTestId("ist-clock")).toHaveText(/^\w{3} \d{2} \w{3} \d{4} · \d{2}:\d{2}:\d{2} IST$/);
  await expect(chart).toHaveAttribute("data-tf", "1m"); // default landing view
  await expect.poll(async () => Number(await chart.getAttribute("data-bars"))).toBeGreaterThan(1000);
  // NVS is on by default and runs on the chart's own timeframe: 18 entries on 1m (15 on 5m, checked below)
  await expect(page.getByTestId("status-pine.nvs_scalper")).toHaveText("ready", { timeout: 45_000 });
  await expect(chart).toHaveAttribute("data-entry-markers", "18");
  await expect(page.getByTestId("engine-panel").filter({ hasText: "pine.nvs_scalper" })).toContainText("VWAP");
  const nOverlays = Number(await chart.getAttribute("data-overlays"));
  expect(nOverlays).toBeGreaterThan(15);
  await expect(page.getByTestId("legend-c")).toHaveText(/^\d+\.\d\d$/);
  const bars1m = Number(await chart.getAttribute("data-bars"));

  await page.locator('button[data-tf="5m"]').click();
  await expect(chart).toHaveAttribute("data-tf", "5m");
  await expect(chart).toHaveAttribute("data-entry-markers", "15", { timeout: 45_000 });
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

  const overlays5m = Number(await chart.getAttribute("data-overlays")); // NVS on the 5m chart
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
  await expect.poll(async () => Number(await chart.getAttribute("data-overlays"))).toBeGreaterThan(overlays5m); // audit lines
  await expect.poll(async () => Number(await chart.getAttribute("data-bars"))).toBeGreaterThan(100);
  if (SHOT) await page.screenshot({ path: SHOT.replace(/\.png$/, "-audit.png") });

  // Balu: toggle it on, zones/rails/markers load and its 13-row panel card renders
  const plotsBefore = Number(await chart.getAttribute("data-plots"));
  const overlaysBefore = Number(await chart.getAttribute("data-overlays"));
  const toggle = page.getByLabel("Toggle pine.balu_zone");
  await toggle.click(); // the switch flips once the saved preference round-trips
  await expect(toggle).toBeChecked();
  await expect(page.getByTestId("status-pine.balu_zone")).toHaveText("ready", { timeout: 60_000 });
  await expect.poll(async () => Number(await chart.getAttribute("data-plots"))).toBeGreaterThan(plotsBefore);
  await expect.poll(async () => Number(await chart.getAttribute("data-overlays"))).toBeGreaterThan(overlaysBefore + 100);
  const balu = page.getByTestId("engine-panel").filter({ hasText: "pine.balu_zone" });
  await expect(balu.locator(".prow")).toHaveCount(13);
  await expect(balu).toContainText("Not established");
  if (SHOT) await page.screenshot({ path: SHOT.replace(/\.png$/, "-balu.png") });
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  await expect(balu).toHaveCount(0);

  // Options on the SYNTHETIC fixture: strike type + expiry -> ATM row, contract chart, honest Greeks
  await page.getByRole("button", { name: "Options", exact: true }).click();
  await expect(page.getByTestId("atm-strike")).toHaveText("25000");
  await expect(page.getByTestId("atm-row")).toBeVisible();
  await page.getByLabel("Strike type").selectOption("ITM");
  await expect(page.locator("tr.picked")).toHaveAttribute("data-strike", "24900"); // CE ITM = ATM - 2 steps
  await page.getByLabel("Option type").selectOption("PE");
  await expect(page.locator("tr.picked")).toHaveAttribute("data-strike", "25100"); // PE mirrored
  await page.getByLabel("Strike type").selectOption("ATM");
  await page.getByLabel("Option type").selectOption("CE");
  await expect(page.getByTestId("contract-panel")).toContainText("25000CE");
  await expect(page.getByTestId("chart")).toHaveAttribute("data-bars", "3"); // the contract's recorded 1m bars
  await expect(page.getByTestId("oi-chart")).toHaveAttribute("data-points", "3");
  await expect(page.getByTestId("greeks")).toContainText("Greeks n/a: set r in Settings");
  await page.getByLabel("Expiry kind").selectOption("monthly");
  await expect(page.getByTestId("expiry-date")).not.toHaveText(/unavailable/);
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByLabel("Risk-free rate").fill("6.5");
  await page.getByRole("button", { name: "Save options settings" }).click();
  await expect(page.getByTestId("options-settings").getByRole("status")).toHaveText("saved");
  await page.getByRole("button", { name: "Options", exact: true }).click();
  await page.getByLabel("Expiry kind").selectOption("current weekly");
  await expect(page.getByTestId("greeks")).toContainText("computed", { timeout: 15_000 });

  // research: oracle data has 17 sessions => inconclusive, with the failed/passed conditions listed
  await page.getByRole("button", { name: "Research", exact: true }).click();
  await page.getByTestId("run-research").click();
  await expect(page.getByTestId("rs-verdict")).toHaveAttribute("data-verdict", "inconclusive", { timeout: 120_000 });
  await expect(page.getByTestId("rs-verdict")).toContainText("insufficient sessions");
  await expect(page.getByTestId("rs-detail")).toContainText("at least 60 sessions");
  await expect(page.getByTestId("rs-table").locator("tbody tr")).toHaveCount(8);
  await expect(page.getByTestId("ci-chart").locator("canvas")).toHaveCount(1);
  await page.getByTestId("label-row").first().click();
  await expect(page.getByTestId("rs-diag")).toContainText(/(BEARISH INDEX \/ PUT|BULLISH INDEX \/ CALL) CANDIDATE/);
  await expect(page.getByTestId("rs-detail")).not.toContainText(/independent confirmations/i);
  await page.getByTestId("rs-open-chart").click();
  await expect(chart).toBeVisible();

  // market context: one box with a line per writing rule; the oracle has no option data, so it shows n/a;
  // each sidebar switch removes only its own rule line, both off hide the box; the header collapses it
  const ctx = page.getByTestId("context-box");
  const ruleIv = page.getByTestId("ctx-rule-iv");
  const ruleOi = page.getByTestId("ctx-rule-oi");
  await expect(ctx).toBeVisible();
  await expect(ctx).toHaveAttribute("data-na", "1");
  await expect(ctx).toContainText(/n\/a|no /);
  await expect(ctx).toContainText("Market context");
  await expect(ctx).toHaveAttribute("data-bias-iv", "NONE");
  await expect(ctx).toHaveAttribute("data-bias-oi", "NONE");
  await expect(ruleIv).toContainText("OI+IV");
  await expect(ruleOi).toContainText("Raw OI");
  const ivToggle = page.getByLabel("Toggle market context OI+IV");
  const oiToggle = page.getByLabel("Toggle market context raw OI");
  await ivToggle.click();
  await expect(ruleIv).toHaveCount(0);
  await expect(ctx).not.toHaveAttribute("data-bias-iv", /.*/);
  await expect(ruleOi).toBeVisible();
  await oiToggle.click();
  await expect(ctx).toHaveCount(0);
  await ivToggle.click();
  await expect(ruleIv).toBeVisible();
  await expect(ruleOi).toHaveCount(0);
  await expect(ctx).not.toHaveAttribute("data-bias-oi", /.*/);
  await oiToggle.click();
  await expect(ruleOi).toBeVisible();
  const head = page.getByTestId("ctx-head");
  await head.click();
  await expect(ctx).toHaveAttribute("data-collapsed", "1");
  await expect(head).toHaveText("– NONE (IV) · – NONE (OI) · room n/a");
  await expect(ruleIv).toHaveCount(0);
  await head.click();
  await expect(ctx).not.toHaveAttribute("data-collapsed", /.*/);
  await expect(ruleIv).toBeVisible();

  // analytics page renders its charts
  await page.getByRole("button", { name: "Analytics", exact: true }).click();
  await expect(page.getByTestId("equity")).toBeVisible();
  await expect(page.getByTestId("session-hist").locator("canvas")).toHaveCount(1);

  // settings: Kite status badge (no live Kite call is made without a token)
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByTestId("kite-badge")).toHaveText(/not (configured|connected)/);

  expect(problems).toEqual([]);
});
