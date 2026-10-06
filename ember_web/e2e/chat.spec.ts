import { expect, test } from "@playwright/test";
import { ACCOUNT, ANSWER, installFakeApi, PASSWORD } from "./fakeApi.ts";

const QUESTION = "What is the capital of France?";

test("log in, ask a question and read the streamed answer", async ({ page }) => {
  const api = await installFakeApi(page);

  // Not logged in: the app sends the visitor to the login page.
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);

  // A wrong password is refused and the page stays on the login form.
  await page.getByLabel("Username").fill(ACCOUNT.username);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByText("Wrong username or password")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);

  // The right one lands on the chat page.
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  const input = page.getByPlaceholder(/Ask something/);
  await expect(input).toBeVisible();
  await expect(page.getByText("Talking to Test Agent")).toBeVisible();
  // The agent picker is gone: ember_api chooses the agent.
  await expect(page.locator("#agent-select")).toHaveCount(0);

  // Ask, with Enter.
  await input.fill(QUESTION);
  await input.press("Enter");

  // While the delegated agent works, the page names who is working.
  await expect(page.getByText("Test Agent → Calculator")).toBeVisible();

  // The question and the streamed answer are both on the page.
  await expect(page.getByText(QUESTION).first()).toBeVisible();
  await expect(page.getByText(ANSWER)).toBeVisible();

  // What the browser sent: the question, no agent id, no tool approval asked for.
  expect(api.turns).toHaveLength(1);
  expect(api.turns[0]).toMatchObject({ question: QUESTION });
  expect(api.turns[0]).not.toHaveProperty("ask_before_tools");

  // The answer carries the agent (the usage chip, not the header tag) and its usage, and the chat is in the sidebar and the address bar.
  await expect(page.getByText(/Test Agent · test-model/)).toBeVisible();
  await expect(page.getByText(/120 tokens|120 tok/i).first()).toBeVisible();
  await expect(page).toHaveURL(/\/chat\/[A-Za-z0-9-]+$/);
  await expect(page.getByRole("complementary").getByText(QUESTION)).toBeVisible();

  // Reloading keeps the chat: it is read back from the server, answer and all.
  await page.reload();
  await expect(page.getByText(ANSWER)).toBeVisible();

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("make a folder, file and pin a chat, then delete the folder with it", async ({ page }) => {
  const api = await installFakeApi(page);
  api.chats.set("seed-chat-0001", {
    id: "seed-chat-0001",
    title: "Seeded chat",
    agent_id: "agent-1",
    messages: [
      { role: "user", content: "hi" },
      { role: "assistant", content: "hello" },
    ],
    running: false,
  });

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(ACCOUNT.username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByPlaceholder(/Ask something/)).toBeVisible();

  const sidebar = page.getByRole("complementary");
  const chatRow = sidebar.getByRole("listitem").filter({ hasText: "Seeded chat" });
  await expect(chatRow).toBeVisible();

  // A new folder, from the button under the list.
  await sidebar.getByRole("button", { name: "New folder" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Name").fill("Work");
  await dialog.getByRole("button", { name: "Save" }).click();
  const workHeader = sidebar.getByRole("button", { name: /^Work\b/ });
  await expect(workHeader).toBeVisible();

  // File the chat in it: "Move to..." > "Work".
  await chatRow.getByRole("button", { name: "Chat actions" }).click();
  await page.getByRole("menuitem", { name: "Move to..." }).click();
  await page.getByRole("menuitemradio", { name: "Work" }).click();
  // `has` is looked up inside each section, so it starts from `page`, not the sidebar.
  const workSection = sidebar.locator("section").filter({ has: page.getByRole("button", { name: /^Work\b/ }) });
  await expect(workSection.getByRole("listitem").filter({ hasText: "Seeded chat" })).toBeVisible();
  await expect.poll(() => api.chats.get("seed-chat-0001")?.folder_id).toBe(1);

  // Pin it: a Pinned section appears.
  await chatRow.getByRole("button", { name: "Chat actions" }).click();
  await page.getByRole("menuitem", { name: "Pin" }).click();
  const pinnedHeader = sidebar.getByRole("heading", { name: /^Pinned\b/ });
  await expect(pinnedHeader).toBeVisible();
  await expect.poll(() => api.chats.get("seed-chat-0001")?.pinned).toBe(true);

  // Delete the folder: its chat goes with it, pinned or not (it kept its folder when pinned).
  await sidebar.getByRole("button", { name: "Folder actions" }).click();
  await page.getByRole("menuitem", { name: "Delete" }).click();
  await expect(dialog).toContainText(`Delete folder "Work" and its 1 chat? This can't be undone.`);
  await dialog.getByRole("button", { name: "Delete" }).click();
  await expect(workHeader).toHaveCount(0);
  await expect(pinnedHeader).toHaveCount(0);
  expect(api.chats.has("seed-chat-0001")).toBe(false);

  // After a reload the server's state shows the same: the chat and both headers are gone.
  await page.reload();
  await expect(page.getByPlaceholder(/Ask something/)).toBeVisible();
  await expect(sidebar.getByRole("listitem").filter({ hasText: "Seeded chat" })).toHaveCount(0);
  await expect(sidebar.getByRole("button", { name: /^Work/ })).toHaveCount(0);
  await expect(sidebar.getByRole("heading", { name: /^Pinned/ })).toHaveCount(0);

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});

test("drag chats onto a folder and onto Pinned", async ({ page }) => {
  const api = await installFakeApi(page);
  api.folders.set(1, { id: 1, name: "Work", position: 1 });
  for (const [id, title] of [["seed-chat-0001", "Alpha"], ["seed-chat-0002", "Beta"]] as const) {
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
  }

  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Username").fill(ACCOUNT.username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(page.getByPlaceholder(/Ask something/)).toBeVisible();

  const sidebar = page.getByRole("complementary");
  const row = (title: string) => sidebar.getByRole("listitem").filter({ hasText: title });
  // `has` is looked up inside each section, so it starts from `page`, not the sidebar.
  const workHeader = page.getByRole("button", { name: /^Work\b/ });
  const workSection = sidebar.locator("section").filter({ has: workHeader });
  const pinnedSection = sidebar.locator("section").filter({ has: page.getByRole("heading", { name: /^Pinned\b/ }) });
  const chatsSection = sidebar.locator("section").filter({ has: page.getByRole("heading", { name: /^Chats\b/ }) });
  await expect(row("Alpha")).toBeVisible();
  await expect(row("Beta")).toBeVisible();

  // Drag by hand: press on the row, move a little so the drag starts, wait until the zone
  // takes the drop, then go to it (read where it is only now) and let go. `dragTo` is not
  // enough: it reads the target's place before the drag starts, but the empty Pinned and
  // Chats zones appear once it starts and push the sections below them down.
  async function dragByHand(title: string, zone: typeof workSection): Promise<void> {
    await row(title).hover();
    const box = (await row(title).boundingBox())!;
    const x = box.x + box.width / 2;
    const y = box.y + box.height / 2;
    await page.mouse.down();
    await page.mouse.move(x + 5, y + 5, { steps: 5 });
    await expect(zone).toBeVisible();
    await expect(zone).toHaveClass(/\baccepting\b/);
    await zone.hover();
    await page.mouse.up();
  }

  // Alpha onto the Work folder: it is filed there.
  await dragByHand("Alpha", workSection);
  await expect.poll(() => api.chats.get("seed-chat-0001")?.folder_id).toBe(1);
  await expect(workSection.getByRole("listitem").filter({ hasText: "Alpha" })).toBeVisible();

  // Beta onto Pinned: it is pinned.
  await dragByHand("Beta", pinnedSection);
  await expect.poll(() => api.chats.get("seed-chat-0002")?.pinned).toBe(true);
  await expect(pinnedSection.getByRole("listitem").filter({ hasText: "Beta" })).toBeVisible();

  // Alpha, from Work, onto Chats: every chat is filed or pinned, so that zone too appears only while dragging.
  await dragByHand("Alpha", chatsSection);
  await expect.poll(() => api.chats.get("seed-chat-0001")?.folder_id).toBeNull();
  await expect(chatsSection.getByRole("listitem").filter({ hasText: "Alpha" })).toBeVisible();

  // The fake knew every request the page made.
  expect(api.unexpected).toEqual([]);
});
