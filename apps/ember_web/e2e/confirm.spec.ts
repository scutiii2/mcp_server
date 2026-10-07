import { expect, test } from "@playwright/test";
import { ANSWER, installFakeApi, type FakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

/** A chat with two exchanges, so editing the first question has later messages to drop. */
const seedTwoExchanges = (api: FakeApi) =>
  api.chats.set("seed-chat-0001", {
    id: "seed-chat-0001",
    title: "Seeded chat",
    agent_id: "agent-1",
    messages: [
      { role: "user", content: "first question" },
      { role: "assistant", content: "first answer" },
      { role: "user", content: "second question" },
      { role: "assistant", content: "second answer" },
    ],
    running: false,
  });

async function openSeededChat(page: import("@playwright/test").Page): Promise<void> {
  await page.getByRole("complementary").getByRole("listitem").filter({ hasText: "Seeded chat" }).click();
  await expect(page).toHaveURL(/\/chat\/seed-chat-0001$/);
  await expect(page.getByText("second answer")).toBeVisible();
}

test("editing a question that has later messages asks before dropping them", async ({ page }) => {
  const api = await installFakeApi(page);
  seedTwoExchanges(api);
  await logIn(page);
  await openSeededChat(page);

  // Edit the first question; the edit box opens with its text.
  await page.getByRole("button", { name: "Edit and resend" }).first().click();
  const box = page.getByRole("textbox", { name: "Edit your question" });
  await expect(box).toHaveValue("first question");
  await box.fill("first question, reworded");
  await page.getByRole("button", { name: "Save & resend" }).click();

  // It asks; Cancel leaves the edit open and sends nothing.
  const dialog = page.getByRole("dialog", { name: "Edit question" });
  await expect(dialog).toContainText("Editing this question discards the messages after it. Continue?");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(box).toHaveValue("first question, reworded");
  expect(api.turns).toHaveLength(0);

  // Confirm: the edited question is sent, cutting the chat back to before it.
  await page.getByRole("button", { name: "Save & resend" }).click();
  await dialog.getByRole("button", { name: "Discard and resend" }).click();
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]).toMatchObject({ question: "first question, reworded", truncate_to: 0 });

  // The later exchange is gone from the page, and the new answer streams in.
  await expect(page.getByText(ANSWER)).toBeVisible();
  await expect(page.getByText("second question")).toHaveCount(0);
  await expect(page.getByText("second answer")).toHaveCount(0);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("editing the last question needs no confirmation", async ({ page }) => {
  const api = await installFakeApi(page);
  seedTwoExchanges(api);
  await logIn(page);
  await openSeededChat(page);

  await page.getByRole("button", { name: "Edit and resend" }).last().click();
  await page.getByRole("textbox", { name: "Edit your question" }).fill("second question, reworded");
  await page.getByRole("button", { name: "Save & resend" }).click();

  // Nothing after it to lose: it is sent at once, with no dialog.
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]).toMatchObject({ question: "second question, reworded", truncate_to: 2 });
  await expect(page.getByRole("dialog", { name: "Edit question" })).toHaveCount(0);
  await expect(page.getByText("first answer")).toBeVisible();

  expect(api.unexpected).toEqual([]);
});

test("turning a share link off asks first, in a dialog over the share dialog", async ({ page }) => {
  const api = await installFakeApi(page);
  seedTwoExchanges(api);
  for (const id of [1, 2]) {
    api.shares.set(id, {
      id,
      chat_id: "seed-chat-0001",
      title: "Seeded chat",
      message_count: 4,
      created_at: `2026-10-0${id}T10:00:00`,
      expires_at: null,
    });
  }
  await logIn(page);
  await openSeededChat(page);

  await page.getByRole("button", { name: "Share", exact: true }).click();
  const share = page.getByRole("dialog", { name: "Share this chat" });
  const links = share.locator(".links li");
  await expect(links).toHaveCount(2);

  // Turn the first one off: the question appears on top of the share dialog; Cancel keeps both.
  await links.first().getByRole("button", { name: "Turn off" }).click();
  const confirm = page.getByRole("dialog", { name: "Turn off link" });
  await expect(confirm).toContainText("Anyone who has it will no longer be able to open the chat.");
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toHaveCount(0);
  await expect(share).toBeVisible();
  await expect(links).toHaveCount(2);
  expect(api.shares.size).toBe(2);

  // Confirm: that link is revoked, the other stays.
  await links.first().getByRole("button", { name: "Turn off" }).click();
  await confirm.getByRole("button", { name: "Turn off" }).click();
  await expect(links).toHaveCount(1);
  expect(api.shares.has(1)).toBe(false);
  expect(api.shares.has(2)).toBe(true);

  expect(api.unexpected).toEqual([]);
});

test("deleting a saved prompt asks first", async ({ page }) => {
  const api = await installFakeApi(page);
  for (const [id, name] of [[1, "Summarize"], [2, "Review"]] as const) {
    api.templates.set(id, { id, name, body: `${name} this text`, created_at: "2026-10-01T10:00:00", updated_at: "2026-10-01T10:00:00" });
  }
  await logIn(page);

  // The prompt picker, then "Manage ..." opens the dialog with the list.
  await page.getByRole("button", { name: "Saved prompts" }).click();
  await page.getByRole("button", { name: "Manage …" }).click();
  const manager = page.getByRole("dialog", { name: "Saved prompts" });
  const rows = manager.locator(".list li");
  await expect(rows).toHaveCount(2);

  // Delete the first: Cancel keeps it and the server is not asked.
  await rows.first().getByRole("button", { name: "Delete" }).click();
  const confirm = page.getByRole("dialog", { name: "Delete prompt" });
  await expect(confirm).toContainText('Delete the prompt "Summarize"?');
  await confirm.getByRole("button", { name: "Cancel" }).click();
  await expect(confirm).toHaveCount(0);
  await expect(rows).toHaveCount(2);
  expect(api.templates.size).toBe(2);

  // Confirm: it is gone from the list and the server.
  await rows.first().getByRole("button", { name: "Delete" }).click();
  await confirm.getByRole("button", { name: "Delete" }).click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText("Review");
  expect(api.templates.has(1)).toBe(false);

  expect(api.unexpected).toEqual([]);
});

test("deleting a role: one that accounts hold needs its name typed, an unused one does not", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.getByRole("link", { name: "Admin", exact: true }).click();
  await page.getByRole("button", { name: "Roles", exact: true }).click();
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

test("switching a capability asks first: off is a danger confirm, on a plain one", async ({ page }) => {
  const api = await installFakeApi(page, { admin: true });
  await logIn(page);
  await page.getByRole("link", { name: "Capabilities", exact: true }).click();
  await expect(page).toHaveURL(/\/capabilities$/);

  const card = (label: string) => page.locator("article.card").filter({ has: page.getByRole("heading", { name: label }) });
  await expect(card("PDF files")).toContainText("1 tool");
  await expect(card("Legacy")).toContainText("1 tool");

  // Turn PDF files off: it asks, and Cancel changes nothing.
  await card("PDF files").getByTitle("Turn off").click();
  const dialog = page.getByRole("dialog", { name: "Turn off capability" });
  await expect(dialog).toContainText('Turn off "PDF files" for every mcp_server client (chat_app, agents, ember)?');
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.capabilities.get("pdf")?.enabled).toBe(true);
  await expect(card("PDF files")).toContainText("1 tool");

  // Confirm: turning off is the risky way round, so the button has the danger style. It is then off
  // here and on the server, and the tools mcp_server lists no longer include its tool.
  await card("PDF files").getByTitle("Turn off").click();
  const turnOff = dialog.getByRole("button", { name: "Turn off" });
  await expect(turnOff).toHaveClass(/danger/);
  await turnOff.click();
  await expect.poll(() => api.capabilities.get("pdf")?.enabled).toBe(false);
  await expect(card("PDF files")).toContainText("off");
  await expect(card("Legacy")).toContainText("1 tool");

  // Turn it back on: a plain confirm, no danger style.
  await card("PDF files").getByTitle("Turn on").click();
  const onDialog = page.getByRole("dialog", { name: "Turn on capability" });
  await expect(onDialog).toContainText('Turn on "PDF files" for every mcp_server client');
  const turnOn = onDialog.getByRole("button", { name: "Turn on" });
  await expect(turnOn).not.toHaveClass(/danger/);
  await turnOn.click();
  await expect.poll(() => api.capabilities.get("pdf")?.enabled).toBe(true);
  await expect(card("PDF files")).toContainText("1 tool");

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});
