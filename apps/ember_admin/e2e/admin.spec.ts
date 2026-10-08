import { expect, test } from "@playwright/test";
import { installFakeApi, newState } from "./fakeApi.ts";

test("the Ember rail moves to the bottom on mobile and remembers the theme", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);
  await page.goto("/capabilities");
  const rail = page.getByRole("complementary", { name: "Ember Admin" });
  const nav = page.getByRole("navigation", { name: "Admin sections" });
  await expect(nav.getByRole("link")).toHaveCount(8);
  await expect(nav.getByRole("link", { name: "Capabilities", exact: true })).toHaveAttribute("aria-current", "page");
  for (const width of [1280, 768, 375]) {
    await page.setViewportSize({ width, height: 800 });
    const box = await rail.boundingBox();
    expect(box).not.toBeNull();
    if (width >= 768) {
      expect(box!.width).toBe(52);
      expect(box!.x).toBe(0);
    } else {
      expect(box!.height).toBe(52);
      expect(box!.y + box!.height).toBe(800);
    }
    expect(await page.evaluate<boolean>("document.documentElement.scrollWidth <= window.innerWidth")).toBe(true);
    await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
  }
  await page.getByRole("button", { name: /^Theme: System/ }).click();
  await page.getByRole("button", { name: /^Theme: Light/ }).click();
  expect(await page.evaluate<string>("document.documentElement.style.colorScheme")).toBe("dark");
  await page.reload();
  await expect(page.getByRole("button", { name: /^Theme: Dark/ })).toBeVisible();
  await nav.getByRole("link", { name: "Extensions", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Extensions", exact: true })).toBeVisible();
  expect(state.unexpected).toEqual([]);
});

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
