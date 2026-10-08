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

test("a private extension is added in the Supermarket, enabled, and listed on Capabilities", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.goto("/capabilities/supermarket");

  await page.getByRole("button", { name: "Add your own extension" }).click();
  await page.getByLabel("Label").fill("My notes");
  await page.getByLabel("Address").fill("https://notes.example.com/mcp");
  await page.getByRole("button", { name: "Add header" }).click();
  await page.locator(".header-name").fill("Authorization");
  await page.locator(".header-value").fill("Bearer secret");
  await page.getByRole("dialog").getByRole("button", { name: "Add", exact: true }).click();

  await expect(item(page, "My notes")).toBeVisible();
  await expect(item(page, "My notes").getByText("Not enabled")).toBeVisible();
  await item(page, "My notes").getByRole("button", { name: "Enable My notes" }).click();
  await expect(item(page, "My notes").getByText("1 tool")).toBeVisible();

  await page.getByRole("link", { name: "Back to capabilities" }).click();
  await expect(card(page, "My notes")).toBeVisible();
  await expect(card(page, "My notes").getByText("Private")).toBeVisible();
  expect(api.userExtensions.get("mynotes")?.header_names).toEqual(["Authorization"]);
  expect(api.unexpected).toEqual([]);
});

test("a private extension turned off on Capabilities stays in the Supermarket and can be removed", async ({ page }) => {
  const api = await installFakeApi(page);
  api.userExtensions.set("mynotes", {
    id: "mynotes",
    label: "My notes",
    description: "",
    url: "https://notes.example.com/mcp",
    header_names: [],
    enabled: true,
    status: "connected",
    error: null,
    tools: ["search"],
  });
  await logIn(page);
  await page.getByRole("link", { name: "Capabilities", exact: true }).click();

  await card(page, "My notes").locator("label.toggle").click();
  await expect(card(page, "My notes")).toHaveCount(0);

  await page.getByRole("link", { name: "Supermarket", exact: true }).click();
  await expect(item(page, "My notes").getByText("Not enabled")).toBeVisible();
  await item(page, "My notes").getByRole("button", { name: "Remove My notes" }).click();
  await page.getByRole("button", { name: "Remove", exact: true }).click();
  await expect(item(page, "My notes")).toHaveCount(0);
  expect(api.userExtensions.size).toBe(0);
  expect(api.unexpected).toEqual([]);
});

for (const width of [1280, 768, 375]) {
  test(`capability card opens a tool workspace at ${width}px`, async ({ page }) => {
    const api = await installFakeApi(page, { admin: true });
    await page.setViewportSize({ width, height: 850 });
    await logIn(page);
    await page.goto("/capabilities");
    const pdf = card(page, "PDF files");
    await pdf.locator(".head-button").click();
    const dialog = page.getByRole("dialog", { name: "PDF files", exact: true });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator(".tool-list button").first()).toBeVisible();
    const before = await dialog.boundingBox();
    await dialog.locator(".tool-list button").first().click();
    await expect(dialog.getByRole("button", { name: "Run tool", exact: true })).toBeVisible();
    await page.screenshot({ path: `C:/Users/User/.codex/visualizations/2026/10/08/01a11ae9-61e7-7880-a756-0bfaebed99a6/ember-web-capability-${width}.png` });
    const after = await dialog.boundingBox();
    expect(after?.height).toBe(before?.height);
    const scroll = await page.evaluate(`(() => { const el = document.querySelector('dialog.integration-modal'); return { outer: getComputedStyle(el).overflowY, list: getComputedStyle(el.querySelector(".tool-list")).overflowY, main: getComputedStyle(el.querySelector(".tester")).overflowY }; })()`);
    expect(scroll).toEqual({ outer: "hidden", list: "auto", main: "auto" });
    await dialog.getByLabel("Find a tool").fill("nothing-matches");
    await expect(dialog.getByText("No tools match your search.")).toBeVisible();
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(pdf.getByRole("switch")).toBeChecked();
    expect(api.unexpected).toEqual([]);
  });
}
