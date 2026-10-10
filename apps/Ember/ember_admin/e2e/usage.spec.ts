import { expect, test } from "@playwright/test";
import { installFakeApi, newState } from "./fakeApi.ts";

test("a usage-only observer selects users and exports the loaded user's report", async ({ page }) => {
  const state = newState(); state.permissions = ["usage.all.view"];
  await installFakeApi(page, state);
  const calls: string[] = []; page.on("request", r => { if (r.url().includes("/api/")) calls.push(r.url()); });
  await page.goto("/admin");
  await expect(page.getByRole("link", { name: "Usage", exact: true })).toBeVisible();
  await page.getByRole("link", { name: "Usage", exact: true }).click();
  await expect(page.getByText("Select a user to view their usage.")).toBeVisible();
  const alice = page.getByRole("button", { name: "View usage for alice" });
  await alice.focus(); await page.keyboard.press("Enter");
  const details = page.getByRole("region", { name: "Usage for alice" });
  await expect(details).toBeVisible();
  await expect(details.getByText("Last 12 months", { exact: true })).toBeVisible();
  await expect(details.getByText("agent-2", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "7 days", exact: true }).click();
  await expect(details).toBeVisible();
  await details.getByRole("button", { name: "Model", exact: true }).click();
  await expect(details.getByRole("columnheader", { name: "Model", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "View usage for bob" }).click();
  await expect(page.getByRole("region", { name: "Usage for bob" })).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export .md" }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toContain("usage-bob-7d");
  const stream = await download.createReadStream();
  const chunks: Buffer[] = []; for await (const chunk of stream!) chunks.push(Buffer.from(chunk));
  const exported = Buffer.concat(chunks).toString("utf8");
  expect(exported).toContain("# Token usage - bob"); expect(exported).toContain("Range: 7 days");
  await page.getByRole("button", { name: "View usage for empty" }).click();
  await expect(page.getByRole("region", { name: "Usage for empty" }).getByText("No usage in this period.")).toBeVisible();
  expect(calls.some(url => new URL(url).pathname === "/api/usage")).toBe(false);
  expect(state.unexpected).toEqual([]);
});

test("report errors can be retried and do not allow stale exports", async ({ page }) => {
  const state = newState(); state.permissions = ["usage.all.view"];
  await installFakeApi(page, state); await page.goto("/usage");
  await page.getByRole("button", { name: "View usage for alice" }).click();
  await expect(page.getByRole("region", { name: "Usage for alice" })).toBeVisible();
  state.usageFailure = true;
  await page.getByRole("button", { name: "90 days", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Report unavailable");
  await expect(page.getByRole("button", { name: "Export .md" })).toBeDisabled();
  state.usageFailure = false;
  await page.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("region", { name: "Usage for alice" })).toBeVisible();
  expect(state.unexpected).toEqual([]);
});

test("Usage is denied without usage.all.view", async ({ page }) => {
  const state = newState(); state.permissions = ["extensions.manage"];
  await installFakeApi(page, state); await page.goto("/usage");
  await expect(page).toHaveURL(/\/admin$/);
  await expect(page.getByRole("link", { name: "Usage", exact: true })).toHaveCount(0);
  expect(state.unexpected).toEqual([]);
});

test("usage remains keyboard-accessible and within the viewport in both themes", async ({ page }) => {
  const state = newState(); state.permissions = ["usage.all.view"];
  state.usageAgent = "agent_" + "long_".repeat(22);
  await installFakeApi(page, state); await page.goto("/usage");
  await page.getByRole("button", { name: "View usage for alice" }).click();
  await expect(page.getByRole("region", { name: "Usage for alice" })).toBeVisible();
  for (const width of [375, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["light", "dark"]) {
      await page.evaluate(t => { document.documentElement.style.colorScheme = t; }, theme);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      const overflow = await page.locator(".usage-view").evaluate(el => ({
        width: el.clientWidth, scroll: el.scrollWidth,
        offenders: Array.from(el.querySelectorAll("*"))
          .filter(node => node.getBoundingClientRect().right > el.getBoundingClientRect().right + 1)
          .map(node => `${node.tagName}.${node.className}`).slice(0, 12),
      }));
      expect(overflow.scroll, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.width);
      const bob = page.getByRole("button", { name: "View usage for bob" });
      await bob.focus(); await page.keyboard.press("Enter");
      await expect(page.getByRole("region", { name: "Usage for bob" })).toBeVisible();
    }
  }
  expect(state.unexpected).toEqual([]);
});
