import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

test("an administrator's Web Usage remains personal", async ({ page }) => {
  const state = await installFakeApi(page, { admin: true });
  await logIn(page);
  const adminCalls: string[] = [];
  page.on("request", r => { if (r.url().includes("/api/admin/usage")) adminCalls.push(r.url()); });
  await page.goto("/usage");
  await expect(page.getByRole("heading", { name: "Usage", exact: true })).toBeVisible();
  await expect(page.getByText("Review your token usage and account limits.")).toBeVisible();
  await expect(page.getByText("All accounts", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "7 days", exact: true }).click();
  expect(adminCalls).toEqual([]); expect(state.unexpected).toEqual([]);
});
