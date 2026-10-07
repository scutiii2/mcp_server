import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

for (const kind of ["built-in", "extension"] as const) {
  test(`${kind} switch appearance follows the chat preference`, async ({ page }) => {
    const api = await installFakeApi(page, { admin: true });
    if (kind === "extension") {
      await page.route("**/api/extensions", (route) => route.fulfill({
        json: [{ id: "echo", label: "Echo server", description: "", status: "connected", error: null, tools: [] }],
      }));
    }
    await logIn(page);
    await page.getByRole("link", { name: "Capabilities", exact: true }).click();

    const card = page.locator("article.card").filter({
      has: page.getByRole("heading", { name: kind === "built-in" ? "PDF files" : "Echo server", exact: true }),
    });
    const toggle = card.locator("label.toggle");
    const input = card.getByRole("switch");
    if (kind === "extension") {
      await expect(input).not.toBeChecked();
      await toggle.click();
    }
    await expect(input).toBeChecked();
    await expect(toggle.locator(".on")).toBeVisible();

    await toggle.click();
    await expect(card).toHaveClass(/\boff\b/);
    await expect(input).not.toBeChecked();
    await expect(toggle.locator(".off")).toBeVisible();
    await expect(toggle.locator(".on")).toBeHidden();

    await page.reload();
    await expect(input).not.toBeChecked();
    await toggle.click();
    await expect(input).toBeChecked();
    await expect(toggle.locator(".on")).toBeVisible();
    expect(api.unexpected).toEqual([]);
  });
}
