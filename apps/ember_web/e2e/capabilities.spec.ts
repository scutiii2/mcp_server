import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

const card = (page: import("@playwright/test").Page, name: string) =>
  page.locator("article.card").filter({ has: page.getByRole("heading", { name, exact: true }) });
const item = (page: import("@playwright/test").Page, name: string) =>
  page.locator("article.item").filter({ has: page.getByRole("heading", { name, exact: true }) });

test("a built-in capability turned off moves to the Supermarket and can be added back", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.getByRole("link", { name: "Capabilities", exact: true }).click();

  const pdf = card(page, "PDF files");
  await expect(pdf.getByRole("switch")).toBeChecked();
  await pdf.locator("label.toggle").click();
  await expect(pdf).toHaveCount(0);

  await page.getByRole("link", { name: "Supermarket" }).click();
  await expect(page).toHaveURL(/\/capabilities\/supermarket$/);
  await expect(item(page, "PDF files").getByRole("button", { name: "Add PDF files" })).toBeVisible();

  await item(page, "PDF files").getByRole("button", { name: "Add PDF files" }).click();
  await expect(item(page, "PDF files").getByText("Added")).toBeVisible();

  await page.reload();
  await expect(item(page, "PDF files").getByText("Added")).toBeVisible();
  await page.getByRole("link", { name: "Back to capabilities" }).click();
  await expect(card(page, "PDF files")).toBeVisible();
  expect(api.unexpected).toEqual([]);
});

test("an extension is added from the Supermarket and then listed on Capabilities", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await page.route("**/api/extensions", (route) =>
    route.fulfill({
      json: [{ id: "echo", label: "Echo server", description: "", status: "connected", error: null, tools: [] }],
    }),
  );
  await logIn(page);
  await page.goto("/capabilities/supermarket");

  await expect(item(page, "Echo server").getByText("Added")).toHaveCount(0);
  await item(page, "Echo server").getByRole("button", { name: "Add Echo server" }).click();
  await expect(item(page, "Echo server").getByText("Added")).toBeVisible();

  await page.getByRole("button", { name: "Enabled" }).click();
  await expect(page).toHaveURL(/state=enabled/);
  await expect(item(page, "Echo server")).toBeVisible();

  await page.getByRole("link", { name: "Back to capabilities" }).click();
  await expect(card(page, "Echo server")).toBeVisible();
  await expect(card(page, "Echo server").getByRole("switch")).toBeChecked();
  expect(api.unexpected).toEqual([]);
});
