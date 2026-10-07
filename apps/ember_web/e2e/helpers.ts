import { expect, type Page } from "@playwright/test";
import { ACCOUNT, PASSWORD } from "./fakeApi.ts";

/** Flips the switch with this name. The real checkbox is hidden inside its label (the pill or
 * lock is drawn by CSS), so the click goes to the label, the way a person would click it. */
export async function flipSwitch(page: Page, name: string): Promise<void> {
  await page.locator("label").filter({ has: page.getByRole("switch", { name }) }).click();
}

/** Logs in through the form and waits for the chat page, as the first step of a spec. */
export async function logIn(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(ACCOUNT.username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByPlaceholder(/Ask something/)).toBeVisible();
}
