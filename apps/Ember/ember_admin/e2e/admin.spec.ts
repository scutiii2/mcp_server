import { expect, test } from "@playwright/test";
import { installFakeApi, newState } from "./fakeApi.ts";

test("the Ember rail moves to the bottom on mobile and remembers the theme", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);
  await page.goto("/capabilities");
  const rail = page.getByRole("complementary", { name: "Ember Admin" });
  const nav = page.getByRole("navigation", { name: "Admin sections" });
  await expect(nav.getByRole("link")).toHaveCount(7);
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

test("capability and extension cards open their tools and run a schema form", async ({ page }, testInfo) => {
  const state = newState();
  await installFakeApi(page, state);
  await page.route('**/api/extensions', (route) => route.fulfill({ contentType: 'application/json', body: JSON.stringify([{ id: 'notes', label: 'Notes', description: 'Shared notes', status: 'connected', error: null, tools: ['notes__add'] }]) }));
  const calls: unknown[] = [];
  await page.route('**/api/mcp/server', async (route) => {
    if (route.request().method() !== 'POST') return route.fulfill({ status: 405 });
    const body = route.request().postDataJSON();
    if (!('id' in body)) return route.fulfill({ status: 202 });
    let result: unknown = {};
    if (body.method === 'initialize') result = { protocolVersion: '2025-03-26', capabilities: { tools: {} }, serverInfo: { name: 'test', version: '1' } };
    if (body.method === 'tools/list') result = { tools: ['tool_vault_run', 'notes__add'].map((name) => ({ name, title: name === 'notes__add' ? 'Add note' : 'Search vault', description: 'A test tool', inputSchema: { type: 'object', properties: { text: { type: 'string', title: 'Text' } }, required: ['text'] } })) };
    if (body.method === 'tools/call') { calls.push(body.params); result = { content: [{ type: 'text', text: 'Completed successfully' }] }; }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ jsonrpc: '2.0', id: body.id, result }) });
  });
  await page.goto('/capabilities');
  await page.getByRole('searchbox', { name: 'Search capabilities', exact: true }).fill('vault_run');
  await expect(page.locator('[data-test=capability]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Open Vault', exact: true }).click();
  const capability = page.getByRole('dialog', { name: 'Vault', exact: true });
  await expect(capability).toBeVisible();
  await expect(capability.locator(".summary-description")).toContainText("Explore the tools provided by Vault.");
  await expect(capability.locator(".tool-list")).toBeVisible();
  const scrollAreas = await page.evaluate<{ outer: string; list: string }>(`(() => {
    const dialog = document.querySelector('.integration-modal');
    const style = (selector) => getComputedStyle(dialog.querySelector(selector));
    return { outer: style('.tools-modal').overflowY, list: style('.tool-list').overflowY };
  })()`);
  expect(scrollAreas).toEqual({ outer: 'hidden', list: 'auto' });
  const initialHeight = (await capability.boundingBox())!.height;
  await capability.getByRole('button', { name: /Search vault/ }).click();
  await capability.getByRole('textbox', { name: /^Text/ }).fill('hello');
  await capability.getByRole('button', { name: 'Run tool', exact: true }).click();
  await expect(capability.locator('.result')).toContainText('Completed successfully');
  await expect(capability.locator('.tester')).toHaveCSS('overflow-y', 'auto');
  expect((await capability.boundingBox())!.height).toBe(initialHeight);
  await expect(capability.getByRole('searchbox', { name: 'Find a tool' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('ember-tool-modal-desktop.png'), animations: 'disabled' });
  expect(calls[0]).toEqual({ name: 'tool_vault_run', arguments: { text: 'hello' } });
  await capability.getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole('link', { name: 'Extensions', exact: true }).click();
  await page.setViewportSize({ width: 375, height: 800 });
  await page.getByRole('searchbox', { name: 'Search extensions', exact: true }).fill('notes__add');
  await expect(page.locator('[data-test=extension]')).toHaveCount(1);
  await page.getByRole('button', { name: 'Open Notes', exact: true }).click();
  const extension = page.getByRole('dialog', { name: 'Notes', exact: true });
  await expect(extension).toContainText('Shared notes');
  await extension.getByRole('button', { name: /Add note/ }).click();
  await extension.getByRole('textbox', { name: /^Text/ }).fill('note');
  await extension.getByRole('button', { name: 'Run tool', exact: true }).click();
  await expect(extension.locator('.result')).toContainText('Completed successfully');
  await page.screenshot({ path: testInfo.outputPath('ember-tool-modal-mobile.png'), animations: 'disabled' });
  expect(calls[1]).toEqual({ name: 'notes__add', arguments: { text: 'note' } });
  expect(await page.evaluate<boolean>("document.documentElement.scrollWidth <= window.innerWidth")).toBe(true);
  expect(state.unexpected).toEqual([]);
});
