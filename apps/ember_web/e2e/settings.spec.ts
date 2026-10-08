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
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await page.reload();
  await expect(page.getByRole("switch", { name: "Terse replies" })).toBeChecked();
  await expect(page.getByText("1 modified")).toBeVisible();

  // The theme: a fixed choice changes the page's colour scheme, its reset goes back to System.
  expect(await colorScheme(page)).toBe("light dark");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Dark" }).click();
  expect(await colorScheme(page)).toBe("light dark");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect(await colorScheme(page)).toBe("dark");
  await expect(page.getByText("2 modified")).toBeVisible();
  await page.getByRole("button", { name: "Reset Theme to its default" }).click();
  expect(await colorScheme(page)).toBe("dark");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  expect(await colorScheme(page)).toBe("light dark");

  // Reset the last one: the badge goes away.
  await page.getByRole("button", { name: "Reset Terse replies to its default" }).click();
  await expect(page.getByRole("switch", { name: "Terse replies" })).not.toBeChecked();
  await expect(page.getByText(/\d+ modified/)).toHaveCount(0);

  await page.getByRole("button", { name: "Save", exact: true }).click();

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("workspace tool approval stays in Admin even for administrators", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.goto("/settings");
  await expect(page.getByRole("switch", { name: "Require approval for every tool" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Admin", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Analytics", exact: true })).toHaveCount(0);
  expect(api.unexpected).toEqual([]);
});

test("page headings and horizontal margins match across content pages", async ({ page }) => {
  await installFakeApi(page);
  await logIn(page);
  for (const width of [1280, 768, 375]) {
    await page.setViewportSize({ width, height: 812 });
    let baseline: unknown;
    for (const route of ['/overview', '/usage', '/settings', '/capabilities', '/capabilities/supermarket']) {
      await page.goto(route);
      await expect(page.locator('.page-title')).toBeVisible();
      const appearance = await page.evaluate(`(() => {
 const title = document.querySelector('.page-title');
 const column = document.querySelector('.page-column');
 const style = getComputedStyle(title);
 const description = document.querySelector('.page-description');
 const desc = description && getComputedStyle(description);
 return { font: style.fontFamily, size: style.fontSize, weight: style.fontWeight, lineHeight: style.lineHeight, left: title.getBoundingClientRect().left, padding: getComputedStyle(column).paddingInlineStart, description: desc && { font: desc.fontFamily, size: desc.fontSize, weight: desc.fontWeight, lineHeight: desc.lineHeight } };
})()`);
      if (baseline) expect(appearance).toEqual(baseline);
      else baseline = appearance;
      expect(await page.evaluate<boolean>('document.documentElement.scrollWidth <= window.innerWidth')).toBe(true);
    }
  }
});

test("settings drafts stay unsaved, can be reverted, and protect navigation", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.goto('/settings');
  await flipSwitch(page, 'Terse replies');
  const bar = page.getByRole('group', { name: 'Unsaved settings' });
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 800 });
    const box = await bar.boundingBox();
    expect(box!.y + box!.height).toBe(width < 768 ? 748 : 800);
  }
  const stored = await page.evaluate("localStorage.getItem('ember_web.caveman')");
  expect(stored).not.toBe('true');
  await bar.getByRole('button', { name: 'Revert' }).click();
  await expect(bar).toHaveCount(0);
  await expect(page.getByRole('switch', { name: 'Terse replies' })).not.toBeChecked();
  await flipSwitch(page, 'Terse replies');
  await page.getByRole('link', { name: 'Capabilities', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Discard unsaved settings?' });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page).toHaveURL(/settings$/);
  await page.getByRole('link', { name: 'Capabilities', exact: true }).click();
  await dialog.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(page).toHaveURL(/capabilities$/);
  expect(api.unexpected).toEqual([]);
});
