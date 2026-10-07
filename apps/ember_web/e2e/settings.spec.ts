import { expect, test, type Page } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { flipSwitch, logIn } from "./helpers.ts";

/** The `color-scheme` the theme control sets on the page: a fixed scheme, or "light dark" for System. */
const colorScheme = (page: Page) => page.evaluate<string>("document.documentElement.style.colorScheme");

test("search, change and reset settings on the Settings page", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);

  // The gear in the nav rail opens the page; a member sees no Administration group.
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await expect(page.getByRole("heading", { name: "Settings", level: 2 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Chat", level: 3 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Appearance", level: 3 })).toBeVisible();
  await expect(page.getByText("Tool approval")).toHaveCount(0);

  // Nothing is changed yet: no badge and no reset buttons.
  await expect(page.getByText(/\d+ modified/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^Reset .* to its default$/ })).toHaveCount(0);

  // Search finds a setting by a keyword it does not show, and hides the rest.
  const search = page.getByRole("searchbox", { name: "Search settings" });
  await search.fill("dark mode");
  await expect(page.getByText("Terse replies")).toHaveCount(0);
  await expect(page.getByText("Light, dark, or follow your system.")).toBeVisible();
  await search.fill("zzz");
  await expect(page.getByText('No settings match "zzz"')).toBeVisible();
  await page.getByRole("button", { name: "Clear search" }).click();
  await expect(search).toHaveValue("");
  await expect(page.getByText("Terse replies")).toBeVisible();

  // Change a chat preference: it is counted, marked and can be reset.
  await flipSwitch(page, "Terse replies");
  await expect(page.getByText("1 modified")).toBeVisible();
  const resetTerse = page.getByRole("button", { name: "Reset Terse replies to its default" });
  await expect(resetTerse).toBeVisible();

  // It is saved in the browser: a reload keeps it.
  await page.reload();
  await expect(page.getByRole("switch", { name: "Terse replies" })).toBeChecked();
  await expect(page.getByText("1 modified")).toBeVisible();

  // The theme: a fixed choice changes the page's colour scheme, its reset goes back to System.
  expect(await colorScheme(page)).toBe("light dark");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Dark" }).click();
  expect(await colorScheme(page)).toBe("dark");
  await expect(page.getByText("2 modified")).toBeVisible();
  await page.getByRole("button", { name: "Reset Theme to its default" }).click();
  expect(await colorScheme(page)).toBe("light dark");

  // Reset the last one: the badge goes away.
  await page.getByRole("button", { name: "Reset Terse replies to its default" }).click();
  await expect(page.getByRole("switch", { name: "Terse replies" })).not.toBeChecked();
  await expect(page.getByText(/\d+ modified/)).toHaveCount(0);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("an administrator saves tool approval through the unsaved bar", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.getByRole("link", { name: "Settings", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);

  const approval = page.getByRole("switch", { name: "Require approval for every tool" });
  const bar = page.getByRole("group", { name: "Unsaved change" });
  await expect(page.getByText("Applies to all accounts")).toBeVisible();
  await expect(bar).toHaveCount(0);

  // Flipping it is only a draft: the bar says who it reaches, and nothing is sent.
  await flipSwitch(page, "Require approval for every tool");
  await expect(bar).toContainText("Turning it on applies to every account");
  expect(api.settings.forceToolApproval).toBe(false);

  // Cancel drops the draft.
  await bar.getByRole("button", { name: "Cancel" }).click();
  await expect(bar).toHaveCount(0);
  await expect(approval).not.toBeChecked();
  expect(api.settings.forceToolApproval).toBe(false);

  // Save sends it, and the setting then counts as modified.
  await flipSwitch(page, "Require approval for every tool");
  await bar.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => api.settings.forceToolApproval).toBe(true);
  await expect(bar).toHaveCount(0);
  await expect(page.getByText("Saved", { exact: true })).toBeVisible();
  await expect(page.getByText("1 modified")).toBeVisible();

  // Back to default is a draft too, until it is saved.
  await page.getByRole("button", { name: "Back to default" }).click();
  await expect(bar).toContainText("Turning it off applies to every account");
  expect(api.settings.forceToolApproval).toBe(true);
  await bar.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => api.settings.forceToolApproval).toBe(false);
  await expect(page.getByText(/\d+ modified/)).toHaveCount(0);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});
