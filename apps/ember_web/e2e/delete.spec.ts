import { expect, test } from "@playwright/test";
import { installFakeApi, type FakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

const seedChats = (api: FakeApi, titles: string[]) => {
  titles.forEach((title, i) => {
    const id = `seed-chat-000${i + 1}`;
    api.chats.set(id, {
      id,
      title,
      agent_id: "agent-1",
      messages: [
        { role: "user", content: "hi" },
        { role: "assistant", content: "hello" },
      ],
      running: false,
    });
  });
};

test("delete one chat: it asks first, and Cancel keeps the chat", async ({ page }) => {
  const api = await installFakeApi(page);
  seedChats(api, ["Alpha", "Beta"]);
  await logIn(page);

  const sidebar = page.getByRole("complementary");
  const row = (title: string) => sidebar.getByRole("listitem").filter({ hasText: title });
  await expect(row("Alpha")).toBeVisible();

  // Cancel in the dialog: the chat stays, the server is not asked.
  await row("Alpha").getByRole("button", { name: "Chat actions" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete chat" });
  await expect(dialog).toContainText('Delete "Alpha"? This can\'t be undone.');
  // One chat asks once: there is no phrase to type.
  await expect(dialog.getByRole("textbox")).toHaveCount(0);
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(row("Alpha")).toBeVisible();
  expect(api.chats.has("seed-chat-0001")).toBe(true);

  // Confirm: the chat goes, here and on the server.
  await row("Alpha").getByRole("button", { name: "Chat actions" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(row("Alpha")).toHaveCount(0);
  await expect(row("Beta")).toBeVisible();
  expect(api.chats.has("seed-chat-0001")).toBe(false);
  expect(api.chats.has("seed-chat-0002")).toBe(true);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("delete all chats needs the phrase typed", async ({ page }) => {
  const api = await installFakeApi(page);
  seedChats(api, ["Alpha", "Beta", "Gamma"]);
  await logIn(page);

  const sidebar = page.getByRole("complementary");
  await expect(sidebar.getByRole("listitem").filter({ hasText: "Gamma" })).toBeVisible();

  await sidebar.getByRole("button", { name: "Delete all chats" }).click();
  const dialog = page.getByRole("dialog", { name: "Delete all chats" });
  await expect(dialog).toContainText("Delete all 3 chats? This can't be undone.");

  // The field has focus at once, and Delete stays locked until the phrase matches exactly.
  const field = dialog.getByRole("textbox");
  const confirm = dialog.getByRole("button", { name: "Delete" });
  await expect(field).toBeFocused();
  await expect(confirm).toBeDisabled();
  await page.keyboard.type("delete al");
  await expect(dialog.getByText("9/10")).toBeVisible();
  await expect(confirm).toBeDisabled();
  expect(api.chats.size).toBe(3);

  await page.keyboard.type("l");
  await expect(dialog.getByText("10/10")).toBeVisible();
  await expect(confirm).toBeEnabled();
  await confirm.click();

  // Every chat is gone, here and on the server.
  await expect.poll(() => api.chats.size).toBe(0);
  await expect(sidebar.getByRole("listitem").filter({ hasText: "Alpha" })).toHaveCount(0);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});
