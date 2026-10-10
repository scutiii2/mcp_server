/// <reference lib="dom" />
import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

test("a first visit picks a starter, then the collection and the Battle tab open", async ({ page }) => {
  const api = await installFakeApi(page, { emberlings: true });
  await logIn(page);
  await page.goto("/emberlings");

  await expect(page.getByRole("button", { name: "New game" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toHaveCount(0);
  await page.getByRole("button", { name: "New game" }).click();
  await expect(page.getByRole("heading", { name: "Choose your first Spark" })).toBeVisible();
  await page.getByRole("radio", { name: "Guardian" }).click();
  await page.getByRole("button", { name: "Start with Guardian" }).click();

  await expect(page.locator(".spark-card")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "Battle", exact: true })).toBeEnabled();
  expect(api.emberlings.keys).toHaveLength(1);
  expect(api.emberlings.keys[0]).toMatch(/^[0-9a-f-]{32,36}$/);
  expect(api.unexpected).toEqual([]);
});
