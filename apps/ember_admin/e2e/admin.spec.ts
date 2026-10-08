import { expect, test } from "@playwright/test";
import { installFakeApi, newState } from "./fakeApi.ts";

test("an admin refreshes, sees a failed load, then brings a fixed capability online", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);

  await page.goto("/capabilities");
  await expect(page.locator("[data-name=vault]")).toHaveAttribute("data-state", "online");
  await expect(page.locator("[data-name=fresh]")).toHaveCount(0);

  // A folder added on disk appears on Refresh, offline.
  await page.locator("[data-test=refresh]").click();
  await expect(page.locator("[data-name=fresh]")).toHaveAttribute("data-state", "new");

  // Going online fails: the row stays offline and shows the error.
  await page.locator("[data-name=fresh] .toggle").click();
  await expect(page.locator("[data-name=fresh] [data-test=row-error]")).toContainText("boom in tool.py");
  await expect(page.locator("[data-name=fresh]")).toHaveAttribute("data-state", "error");

  // The code is fixed; online now works.
  state.failing.delete("fresh");
  await page.locator("[data-name=fresh] .toggle").click();
  await expect(page.locator("[data-name=fresh]")).toHaveAttribute("data-state", "online");

  // Taking a capability offline.
  await page.locator("[data-name=vault] .toggle").click();
  await expect(page.locator("[data-name=vault]")).toHaveAttribute("data-state", "offline");

  expect(state.unexpected).toEqual([]);
});
