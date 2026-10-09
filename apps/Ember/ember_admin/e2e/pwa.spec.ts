/// <reference lib="dom" />
import { expect, test } from "@playwright/test";
import { installFakeApi, newState } from "./fakeApi.ts";

test("production manifest, offline shell, network-only API, and reconnect", async ({ page, context }) => {
  await installFakeApi(page, newState());
  await page.goto("/login");
  const manifestHref = await page.locator('link[rel="manifest"]').getAttribute("href");
  const manifest = await (await page.request.get(manifestHref!)).json();
  expect(manifest.name).toBe("Ember Admin");
  expect(manifest.display).toBe("standalone");
  expect(manifest.start_url).toBe("/admin");
  for (const size of ["192x192", "512x512"]) expect(manifest.icons.some((icon: { sizes: string }) => icon.sizes === size)).toBe(true);
  await page.evaluate(async () => { await navigator.serviceWorker.ready; });
  await page.reload();
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  // Remove API fakes before going offline: otherwise test routing could answer them.
  await page.unrouteAll();
  await context.setOffline(true);
  await page.goto("/settings");
  await expect(page.getByText("You’re offline.")).toBeVisible();
  expect(await page.evaluate(async () => {
    try { await fetch('/api/auth/me'); return false; } catch { return true; }
  })).toBe(true);
  const cached = await page.evaluate(async () => {
    const entries = await Promise.all((await caches.keys()).map(async key => (await (await caches.open(key)).keys()).map(request => new URL(request.url).pathname)));
    return entries.flat();
  });
  expect(cached.some(path => path.startsWith('/api/'))).toBe(false);
  expect(cached.some(path => path.endsWith('/index.html'))).toBe(true);
  await context.setOffline(false);
  await installFakeApi(page, newState());
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByText("You’re offline.")).not.toBeVisible();
});

for (const width of [375, 768]) {
  test(`phone/tablet layout at ${width}px has usable navigation and no page overflow`, async ({ page }) => {
    await page.setViewportSize({ width, height: 812 });
    await installFakeApi(page, newState());
    await page.goto("/capabilities");
    await expect(page.getByRole("heading", { name: "Capabilities", exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.getByRole('link', { name: 'Settings', exact: true }).last()).toBeVisible();
    await page.getByRole('link', { name: 'Settings', exact: true }).last().click();
    await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.getByRole('searchbox', { name: 'Search settings' }).fill('theme');
    if (width < 768) await expect(page.getByRole('searchbox', { name: 'Search settings' })).toHaveCSS('font-size', '16px');
    await expect(page.getByText('Theme', { exact: true }).first()).toBeVisible();
  });
}
