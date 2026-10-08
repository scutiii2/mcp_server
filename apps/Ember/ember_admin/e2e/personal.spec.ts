import { expect, test } from "@playwright/test";
import { ADMIN_ACCOUNT, installFakeApi, newState } from "./fakeApi.ts";

test("profile changes a password and forgets a remembered device after confirmation", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);
  let changed: unknown;
  await page.route("**/api/account/password", route => {
    changed = route.request().postDataJSON();
    return route.fulfill({ json: ADMIN_ACCOUNT });
  });
  await page.route("**/api/account/devices", route => route.fulfill({ json: [{ id: 2, label: "Safari on iPhone", user_agent: "Safari", ip_subnet: "10.0.0.0/24", first_seen_at: "2026-10-01T10:00:00", last_seen_at: "2026-10-08T10:00:00", current: false }] }));
  let forgotten = false;
  await page.route("**/api/account/devices/2", route => { forgotten = true; return route.fulfill({ status: 204 }); });
  await page.goto("/profile");
  await expect(page.getByRole("heading", { name: "Profile", exact: true })).toBeVisible();
  await expect(page.locator(".profile .name")).toHaveText("root");
  await page.getByRole("button", { name: "Change password", exact: true }).click();
  await page.getByLabel("New password", { exact: true }).fill("new-password");
  await page.getByLabel("Repeat new password").fill("different");
  await expect(page.locator("#account-password-form button.primary")).toBeDisabled();
  await page.getByLabel("Repeat new password").fill("new-password");
  await page.getByLabel("Current password").fill("old-password");
  await page.locator("#account-password-form button.primary").click();
  await expect(page.getByRole("status")).toHaveText("Password changed.");
  expect(changed).toEqual({ current_password: "old-password", new_password: "new-password" });
  await page.getByRole("button", { name: "Forget", exact: true }).click();
  expect(forgotten).toBe(false);
  await page.getByRole("dialog").getByRole("button", { name: "Forget", exact: true }).click();
  await expect(page.getByText("None recorded yet.")).toBeVisible();
  expect(forgotten).toBe(true);
  for (const width of [1280, 768, 375]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await page.evaluate<boolean>("document.documentElement.scrollWidth <= innerWidth")).toBe(true);
  }
  expect(state.unexpected).toEqual([]);
});

test("settings saves drafts and persists them on reload", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);
  await page.goto("/settings");
  await page.getByRole("group", { name: "Theme", exact: true }).getByRole("button", { name: "Dark", exact: true }).click();
  const capabilitySwitch = page.getByRole("switch", { name: "Show Capabilities in the sidebar" });
  await capabilitySwitch.focus();
  await capabilitySwitch.press("Space");
  await expect(capabilitySwitch).not.toBeChecked();
  const nav = page.getByRole("navigation", { name: "Admin sections" });
  await expect(nav.getByRole("link", { name: "Capabilities", exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: /^Theme: System/ })).toBeVisible();
  await page.getByRole("button", { name: "Revert", exact: true }).click();
  await expect(capabilitySwitch).toBeChecked();
  await expect(page.getByRole("group", { name: "Unsaved settings" })).toHaveCount(0);
  await page.getByRole("group", { name: "Theme", exact: true }).getByRole("button", { name: "Dark", exact: true }).click();
  await capabilitySwitch.focus();
  await capabilitySwitch.press("Space");
  await page.getByRole("button", { name: "Pin Extensions to the top" }).click();
  for (const width of [1280, 768, 375]) {
    await page.setViewportSize({ width, height: 800 });
    await expect(page.getByRole("button", { name: "Save", exact: true })).toBeVisible();
    const bar = await page.getByRole("group", { name: "Unsaved settings" }).boundingBox();
    expect(bar!.y + bar!.height).toBe(width < 768 ? 748 : 800);
  }
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(nav.getByRole("link", { name: "Capabilities", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link").first()).toHaveAttribute("aria-label", "Extensions");
  await page.reload();
  await expect(page.getByRole("group", { name: "Theme", exact: true }).getByRole("button", { name: "Dark", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(nav.getByRole("link", { name: "Capabilities", exact: true })).toHaveCount(0);
  await page.getByLabel("Search settings").fill("theme");
  await expect(page.getByRole("region", { name: "Sidebar", exact: true })).toHaveCount(0);
  for (const width of [1280, 768, 375]) {
    await page.setViewportSize({ width, height: 800 });
    expect(await page.evaluate<boolean>("document.documentElement.scrollWidth <= innerWidth")).toBe(true);
    await expect(page.getByRole("link", { name: "Profile", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Settings", exact: true })).toBeVisible();
  }
  expect(state.unexpected).toEqual([]);
});

test("changing email completes verification inside Admin", async ({ page }) => {
  const state = newState();
  await installFakeApi(page, state);
  await page.route("**/api/account/devices", route => route.fulfill({ json: [] }));
  await page.route("**/api/account/email", route => route.fulfill({ json: { account: { ...ADMIN_ACCOUNT, email: "new@example.com", email_verified: false }, verification_email_sent: false, email_error: "Email unavailable" } }));
  await page.route("**/api/auth/verify-email/resend", route => route.fulfill({ json: { sent: true } }));
  await page.route("**/api/auth/verify-email", route => route.fulfill({ json: { ...ADMIN_ACCOUNT, email: "new@example.com" } }));
  await page.goto("/profile");
  await page.getByRole("button", { name: "Change email", exact: true }).click();
  await page.getByLabel("New email").fill("new@example.com");
  await page.getByLabel("Current password").fill("old-password");
  await page.locator("#account-email-form button.primary").click();
  await expect(page).toHaveURL(/verify-email\?unsent=1/);
  await expect(page.getByText(/couldn't be sent/)).toBeVisible();
  await page.getByRole("button", { name: "Send a new code" }).click();
  await expect(page.getByText("A new code is on its way.")).toBeVisible();
  await page.getByLabel("Verification code").fill("123456");
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.locator(".profile .email")).toHaveText("new@example.com");
  expect(state.unexpected).toEqual([]);
});
