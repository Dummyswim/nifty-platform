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

  expect(problems).toEqual([]);
});
