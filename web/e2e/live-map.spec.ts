import { expect, test } from "@playwright/test";

// The fixture network: lines A and B, stations Alpha, Bravo, Charlie and Delta, the A line delayed.
// Trains from the fixture feed: a1, a2, b1, plus later A trains that haven't left yet.

test("shows live trains and line status", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("live-count")).toContainText(/\d+ trains live/);
  const count = Number((await page.getByTestId("live-count").innerText()).match(/(\d+) trains/)![1]);
  expect(count).toBeGreaterThanOrEqual(3);

  await expect(page.getByText("1 line delayed")).toBeVisible();
  await page.getByRole("button", { name: "A line" }).click();
  const detail = page.getByTestId("line-detail");
  await expect(detail).toContainText("Delays");
  await expect(detail).toContainText("A trains are running with delays");
});

test("finds a station and shows its next trains by direction", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Find a station").fill("Bravo");
  const panel = page.getByTestId("station-panel");
  await expect(panel.getByRole("heading", { name: "Bravo" })).toBeVisible();
  await expect(panel).toContainText("Uptown / northbound");
  await expect(panel.getByText(/\d+ min/).first()).toBeVisible();
  await expect(panel).toContainText("Downtown / southbound");
});

test("saves a commute and flags it as late when its line is delayed", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Find a station").fill("Bravo");
  const panel = page.getByTestId("station-panel");
  const aRow = panel.locator("li", { has: page.getByLabel("A line") }).first();
  await aRow.getByRole("button", { name: "Save commute" }).click();
  await expect(aRow.getByRole("button", { name: "Saved" })).toBeVisible();

  const commutes = page.getByTestId("commutes");
  await expect(commutes).toContainText("Bravo (A, uptown)");
  await expect(commutes).toContainText("Running late");

  // Saved commutes belong to this browser: they survive a reload.
  await page.reload();
  await expect(page.getByTestId("commutes")).toContainText("Bravo (A, uptown)");

  await page.getByRole("button", { name: "Remove Bravo (A, uptown)" }).click();
  await expect(page.getByText("Pick a station on the map")).toBeVisible();
});
