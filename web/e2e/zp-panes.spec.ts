import { expect, test } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "";

// runs after smoke.spec (alphabetical) and leaves the layout at 1 pane for zz-live.spec
test("layouts 1/2/3, resizable dividers, layout survives reload", async ({ page }) => {
  const problems: string[] = [];
  let loggedIn = false;
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
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
  await expect(panes.nth(2).getByTestId("chart")).toHaveAttribute("data-tf", "5m");
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
