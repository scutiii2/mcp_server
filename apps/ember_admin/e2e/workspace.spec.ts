import { expect, test, type Page } from "@playwright/test";
import { installFakeApi, ACCOUNT, PASSWORD } from "./workspaceFakeApi.ts";

async function flipSwitch(page: Page, name: string): Promise<void> {
  await page.locator("label").filter({ has: page.getByRole("switch", { name }) }).click();
}

// Log in directly to the moved workspace page.
async function logInAdmin(page: Page): Promise<void> {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(ACCOUNT.username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByRole("heading", { name: "Workspace overview", exact: true })).toBeVisible();
}

test("an administrator deletes an account from the Danger zone by typing its name", async ({ page }) => {
  const api = await installFakeApi(page);
  await logInAdmin(page);
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await expect(page).toHaveURL(/\/admin/);
  await page.getByRole('navigation', { name: 'Administration pages' }).getByRole('link', { name: 'Accounts', exact: true }).click();

  // Open maria's drawer: Delete account is in its own Danger zone, not among the edit buttons.
  await page.getByRole("row").filter({ hasText: "maria" }).click();
  const zone = page.locator(".danger-zone");
  await expect(zone).toContainText("Danger zone");
  await expect(zone.getByRole("button", { name: "Delete account" })).toBeVisible();

  // Protected accounts offer no Danger zone at all.
  await page.getByRole('dialog', { name: 'Account maria', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole("row").filter({ hasText: "ada" }).click();
  await expect(page.locator(".danger-zone")).toHaveCount(0);
  await page.getByRole('dialog', { name: 'Account ada', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  await page.getByRole("row").filter({ hasText: "maria" }).click();

  await zone.getByRole("button", { name: "Delete account" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete account" });
  await expect(dialog).toContainText("Delete 'maria' permanently?");
  const field = dialog.getByRole("textbox");
  const confirm = dialog.getByRole("button", { name: "Delete" });
  await expect(field).toBeFocused();
  await expect(confirm).toBeDisabled();

  // A wrong name keeps it locked; the right one unlocks it.
  await page.keyboard.type("mari");
  await expect(confirm).toBeDisabled();
  expect(api.accounts.has(2)).toBe(true);
  await page.keyboard.type("a");
  await expect(confirm).toBeEnabled();
  await confirm.click();

  await expect.poll(() => api.accounts.has(2)).toBe(false);
  await expect(page.getByRole("row").filter({ hasText: "maria" })).toHaveCount(0);
  await expect(page.getByRole("row").filter({ hasText: "joe" })).toBeVisible();

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("an administrator saves tool approval through the unsaved bar", async ({ page }) => {
  const api = await installFakeApi(page);
  await logInAdmin(page);
  await page.getByRole('navigation', { name: 'Administration pages' }).getByRole('link', { name: 'Workspace settings', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/settings/);

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

  // Back to default is a draft too, until it is saved.
  await page.getByRole("button", { name: "Back to default" }).click();
  await expect(bar).toContainText("Turning it off applies to every account");
  expect(api.settings.forceToolApproval).toBe(true);
  await bar.getByRole("button", { name: "Save" }).click();
  await expect.poll(() => api.settings.forceToolApproval).toBe(false);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("deleting a role: one that accounts hold needs its name typed, an unused one does not", async ({ page }) => {
  const api = await installFakeApi(page);
  await logInAdmin(page);
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await page.getByRole('navigation', { name: 'Administration pages' }).getByRole('link', { name: 'Roles & permissions', exact: true }).click();
  const roleButton = (name: string) => page.locator("button.role").filter({ hasText: name });
  await expect(roleButton("Member")).toBeVisible();

  // The protected Administrator role has no Danger zone.
  await roleButton("Administrator").click();
  await expect(page.locator(".danger-zone")).toHaveCount(0);

  // Member is held by an account: its name must be typed.
  await roleButton("Member").click();
  const zone = page.locator(".danger-zone");
  await expect(zone).toContainText("Danger zone");
  await zone.getByRole("button", { name: "Delete role" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete role" });
  await expect(dialog).toContainText("Delete role 'Member'? It is removed from 1 account.");
  const confirm = dialog.getByRole("button", { name: "Delete" });
  await expect(dialog.getByRole("textbox")).toBeFocused();
  await expect(confirm).toBeDisabled();
  await page.keyboard.type("Membe");
  await expect(confirm).toBeDisabled();
  await page.keyboard.type("r");
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect.poll(() => api.roles.has(2)).toBe(false);
  await expect(roleButton("Member")).toHaveCount(0);

  // Ops holds no account: no text to type, the button is ready at once.
  await roleButton("Ops").click();
  await page.locator(".danger-zone").getByRole("button", { name: "Delete role" }).click();
  await expect(dialog).toContainText("It is removed from 0 accounts.");
  await expect(dialog.getByRole("textbox")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect.poll(() => api.roles.has(3)).toBe(false);
  await expect(roleButton("Ops")).toHaveCount(0);

  expect(api.unexpected).toEqual([]);
});

test('overview shortcuts retain account filters across reload and legacy links open their new page', async ({ page }) => {
  const api = await installFakeApi(page);
  await logInAdmin(page);
  await page.locator('.admin-info').getByRole('link', { name: 'Review accounts' }).click();
  await expect(page).toHaveURL(/\/admin\/accounts\?status=unverified/);
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('joe');
  await page.reload();
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await page.goto('/admin?tab=roles&source=bookmark');
  await expect(page).toHaveURL(/\/admin\/roles\?source=bookmark/);
  await expect(page.getByRole('heading', { name: 'Roles & permissions', exact: true })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Admin sections' }).getByRole('link', { name: 'Admin', exact: true })).toHaveAttribute('aria-current', 'page');
  expect(api.unexpected).toEqual([]);
});

test('a role viewer sees only the permitted pages and cannot change permissions', async ({ page }) => {
  const api = await installFakeApi(page, ['roles.view']);
  await logInAdmin(page);
  const nav = page.getByRole('navigation', { name: 'Administration pages' });
  await expect(nav.getByRole('link')).toHaveCount(2);
  await expect(page.locator('.stats')).toHaveCount(0);
  await nav.getByRole('link', { name: 'Roles & permissions', exact: true }).click();
  await expect(page.getByRole('button', { name: '＋ New role', exact: true })).toHaveCount(0);
  await page.locator('button.role').filter({ hasText: 'Member' }).click();
  for (const control of await page.getByRole('switch').all()) await expect(control).toBeDisabled();
  await page.goto('/admin/settings');
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole('heading', { name: 'Workspace overview' })).toBeVisible();
  expect(api.unexpected).toEqual([]);
});

test('invite creation uses a focus-trapped drawer and reveals the new code', async ({ page }) => {
  const api = await installFakeApi(page);
  await logInAdmin(page);
  await page.getByRole('link', { name: '＋ Create invite', exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/invites$/);
  const dialog = page.getByRole('dialog', { name: 'Create invite', exact: true });
  await expect(dialog).toBeVisible();
  await dialog.getByRole('textbox', { name: 'Invitee email' }).fill('new@example.com');
  await dialog.getByRole('button', { name: 'Create invite', exact: true }).click();
  await expect(dialog).toContainText('TEST-INVITE-123');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  expect(api.unexpected).toEqual([]);
});

test('admin pages fit desktop, tablet, and mobile in both themes', async ({ page }) => {
  const api = await installFakeApi(page);
  await logInAdmin(page);
  for (const color of ['light', 'dark']) {
    await page.evaluate((scheme) => { localStorage.setItem('ember_admin.theme', scheme); }, color);
    for (const width of [1280, 768, 375]) {
      await page.setViewportSize({ width, height: 812 });
      for (const route of ['/admin', '/admin/accounts', '/admin/roles', '/admin/invites', '/admin/settings']) {
        await page.goto(route);
        await expect(page.getByRole('navigation', { name: 'Administration pages' })).toBeVisible();
        expect(await page.evaluate<string>('document.documentElement.style.colorScheme')).toBe(color);
        expect(await page.evaluate<boolean>('document.documentElement.scrollWidth <= window.innerWidth')).toBe(true);
      }
    }
  }
  expect(api.unexpected).toEqual([]);
});

