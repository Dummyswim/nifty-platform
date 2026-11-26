import { expect, test } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "";

// runs after smoke.spec (alphabetical) and leaves the layout at 1 pane for zz-live.spec
test("layouts 1/2/3, resizable dividers, layout survives reload", async ({ page }) => {
  const problems: string[] = [];
  let loggedIn = false;
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  page.on("response", (r) => { if (r.status() >= 500) problems.push(`http ${r.status()}: ${r.request().method()} ${r.url()}`); });
  page.on("console", (m) => {
    if (m.type() === "error" && !(!loggedIn && m.text().includes("401"))) problems.push(`console: ${m.text()}`);
  });
  await page.goto("/");
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  loggedIn = true;

  const panes = page.getByTestId("pane");
  await expect(panes).toHaveCount(1);
  await expect(page.getByTestId("divider-col")).toHaveCount(0);
  await page.locator('button[data-tf="1m"]').click(); // smoke.spec leaves pane A on 5m
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tf", "1m");

  await page.getByTestId("layout-2").click();
  await expect(panes).toHaveCount(2);
  await expect(page.getByTestId("divider-row")).toHaveCount(0);

  await page.getByTestId("layout-3").click();
  await expect(panes).toHaveCount(3);
  for (let i = 0; i < 3; i++) {
    await expect.poll(async () => Number(await panes.nth(i).getByTestId("chart").getAttribute("data-bars"))).toBeGreaterThan(100);
  }
  // A is the big left pane: as tall as B + divider + C
  const [a, b, c] = await Promise.all([0, 1, 2].map((i) => panes.nth(i).boundingBox()));
  expect(a!.height).toBeGreaterThan(b!.height + c!.height);
  expect(b!.x).toBeCloseTo(c!.x, 0);

  // clicking a pane makes it active; the timeframe buttons act on it only
  await panes.nth(2).click({ position: { x: 40, y: 40 } });
  await expect(panes.nth(2)).toHaveAttribute("data-active", "true");
  await page.locator('button[data-tf="5m"]').click();
  await expect(panes.nth(2).getByTestId("chart")).toHaveAttribute("data-tf", "5m");
  await expect(panes.nth(0).getByTestId("chart")).toHaveAttribute("data-tf", "1m");

  // option contract in pane C (active): an unrecorded one shows a note, a recorded one shows bars
  // 1m first: the SYNTHETIC option bars are stamped at wall-clock time, off-session when this runs in the
  // evening, and resampling off-session bars to 5m is an error (real recorded bars are always in session)
  await page.locator('button[data-tf="1m"]').click();
  const symbolSel = page.getByLabel("Symbol");
  await symbolSel.selectOption("__option__");
  await expect(page.getByTestId("option-picker")).toBeVisible();
  const unrec = page.locator('[data-testid="pick-PE"][data-recorded="false"]').first();
  if (await unrec.count()) {
    await unrec.click();
    await expect(panes.nth(2).getByTestId("pane-note")).toContainText("no recorded bars");
    await symbolSel.selectOption("__option__");
  }
  // the SYNTHETIC fixture has 1m bars only for strikes 24950/25000/25050 of the nearest expiry
  const rec = page.locator('.picker-row[data-strike="25000"] [data-testid="pick-CE"]');
  const contract = (await rec.getAttribute("title"))!;
  await rec.click();
  await expect(page.getByTestId("option-picker")).toHaveCount(0);
  const optChart = panes.nth(2).getByTestId("chart");
  await expect(optChart).toHaveAttribute("data-symbol", contract);
  await expect.poll(async () => Number(await optChart.getAttribute("data-bars"))).toBeGreaterThan(0);
  await expect(panes.nth(2).getByTestId("pane-note")).toHaveCount(0);
  await expect(panes.nth(2).getByTestId("legend")).toContainText(/ CE/);
  await expect(panes.nth(0).getByTestId("chart")).toHaveAttribute("data-symbol", "NIFTY 50");

  // crosshair sync: hovering pane A puts pane B's crosshair (and legend) on the same 1m bar
  const legendTime = async (i: number) => ((await panes.nth(i).getByTestId("legend").innerText()).split(" O ")[0] ?? "").replace(/^.*· \w+\s*/, "");
  const pa = (await panes.nth(0).boundingBox())!;
  // left part of the pane: the right ~250 px are future whitespace and the price scale
  await page.mouse.move(pa.x + pa.width * 0.3, pa.y + pa.height * 0.5);
  await expect.poll(() => legendTime(0)).not.toBe("");
  await expect.poll(() => legendTime(1)).toBe(await legendTime(0));
  await page.mouse.move(pa.x + pa.width * 0.2, pa.y + pa.height * 0.5);
  await expect.poll(() => legendTime(1)).toBe(await legendTime(0));

  // drag the column divider 100 px right: the left pane grows
  const div = (await page.getByTestId("divider-col").boundingBox())!;
  await page.mouse.move(div.x + div.width / 2, div.y + div.height / 2);
  await page.mouse.down();
  await page.mouse.move(div.x + div.width / 2 + 100, div.y + div.height / 2, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => (await panes.nth(0).boundingBox())!.width).toBeGreaterThan(a!.width + 80);
  const widened = (await panes.nth(0).boundingBox())!.width;

  // drag the row divider up: B gets shorter
  const row = (await page.getByTestId("divider-row").boundingBox())!;
  await page.mouse.move(row.x + row.width / 2, row.y + row.height / 2);
  await page.mouse.down();
  await page.mouse.move(row.x + row.width / 2, row.y + row.height / 2 - 80, { steps: 5 });
  await page.mouse.up();
  await expect.poll(async () => (await panes.nth(1).boundingBox())!.height).toBeLessThan(b!.height - 60);

  // persisted: layout, active pane's timeframe and divider sizes
  await page.waitForTimeout(500); // prefs PUTs are fire-and-forget
  await page.reload();
  await expect(panes).toHaveCount(3);
  await expect(panes.nth(2).getByTestId("chart")).toHaveAttribute("data-tf", "1m");
  await expect(panes.nth(2).getByTestId("chart")).toHaveAttribute("data-symbol", contract);
  await expect.poll(async () => Math.round((await panes.nth(0).boundingBox())!.width)).toBeCloseTo(Math.round(widened), -1);

  // double-click resets the column divider to equal widths
  await page.getByTestId("divider-col").dblclick();
  await expect.poll(async () => Math.abs((await panes.nth(0).boundingBox())!.width - (await panes.nth(1).boundingBox())!.width)).toBeLessThan(260);

  // back to one pane (pane A, 1m) for the next spec
  await page.getByTestId("layout-1").click();
  await expect(panes).toHaveCount(1);
  await expect(page.getByTestId("chart")).toHaveAttribute("data-tf", "1m");
  await page.waitForTimeout(500);
  expect(problems).toEqual([]);
});
