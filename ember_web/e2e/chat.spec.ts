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

  // Ask, with Enter.
  await input.fill(QUESTION);
  await input.press("Enter");

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
