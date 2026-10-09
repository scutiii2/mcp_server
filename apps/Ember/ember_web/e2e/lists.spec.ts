/// <reference lib="dom" />
import { expect, test } from "@playwright/test";
import { installFakeApi } from "./fakeApi.ts";
import { logIn } from "./helpers.ts";

test("bullets format while typing, Shift+Enter continues, and Enter sends Markdown", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).pressSequentially("- first");
  const editor = page.locator(".list-composer");
  await expect(editor.locator("ul > li")).toHaveCount(1);
  await editor.press("Shift+Enter");
  await editor.pressSequentially("second");
  await expect(editor.locator("ul > li")).toHaveCount(2);
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toBe("- first\n- second");
  await expect(page.locator(".composer textarea")).toBeFocused();
  expect(api.unexpected).toEqual([]);
});

test("numbered lists continue their starting number", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).fill("3. third");
  const editor = page.locator(".list-composer");
  await expect(editor.locator("ol")).toHaveAttribute("start", "3");
  await editor.press("Shift+Enter");
  await editor.pressSequentially("fourth");
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toBe("3. third\n4. fourth");
});

test("empty next items exit the list; later lists and undo remain editable", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).fill("- first");
  const editor = page.locator(".list-composer");
  await editor.press("Shift+Enter");
  await editor.press("Shift+Enter");
  await editor.pressSequentially("normal paragraph");
  await expect(editor.locator(":scope > p")).toHaveText("normal paragraph");
  await editor.press("Shift+Enter");
  await editor.pressSequentially("1. later");
  await expect(editor.locator("ol > li")).toHaveCount(1);
  await editor.press("Control+z");
  await editor.press("Control+Shift+z");
  await expect(editor.locator("ol > li")).toHaveCount(1);
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toBe("- first\n\nnormal paragraph\n\n1. later");
});

test("nested lists indent and outdent with Tab and Shift+Tab", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).fill("- first\n- second");
  const editor = page.locator(".list-composer");
  await editor.press("Tab");
  await expect(editor.locator("ul ul > li")).toHaveCount(1);
  await editor.press("Shift+Tab");
  await expect(editor.locator("ul ul")).toHaveCount(0);
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toBe("- first\n- second");
});

test("mobile wrapped items use hanging indentation and a usable font", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).fill("- A long item with enough words to wrap onto several lines in the narrow phone composer while staying aligned.");
  const editor = page.locator(".list-composer");
  await expect(editor).toHaveCSS("font-size", "16px");
  await expect(editor.locator("ul")).toHaveCSS("list-style-type", "disc");
  const geometry = await editor.evaluate(element => {
    const list = element.querySelector("ul")!;
    const paragraph = element.querySelector("li p")!;
    return { indent: paragraph.getBoundingClientRect().left - element.getBoundingClientRect().left,
      padding: parseFloat(getComputedStyle(list).paddingLeft), height: paragraph.getBoundingClientRect().height,
      line: parseFloat(getComputedStyle(paragraph).lineHeight), overflow: document.documentElement.scrollWidth > innerWidth };
  });
  expect(geometry.indent).toBeGreaterThan(0);
  expect(geometry.indent).toBeCloseTo(geometry.padding, 0);
  expect(geometry.height).toBeGreaterThan(geometry.line);
  expect(geometry.overflow).toBe(false);
});

test("pasted text becomes editable lists and pasted HTML stays literal", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).fill("- first");
  const editor = page.locator(".list-composer");
  await editor.press("Control+End");
  await editor.press("Shift+Enter");
  await editor.evaluate(element => {
    const clipboard = new DataTransfer();
    clipboard.setData("text/plain", "<img src=x onerror=alert(1)>");
    clipboard.setData("text/html", "<img src=x onerror=alert(1)>");
    element.dispatchEvent(new ClipboardEvent("paste", { clipboardData: clipboard, bubbles: true, cancelable: true }));
  });
  await expect(editor.locator("img, script")).toHaveCount(0);
  await expect(editor).toContainText("<img src=x onerror=alert(1)>");
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toContain("<img src=x onerror=alert(1)>");
});

test("formatting a line preserves the caret in the middle of a draft", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  const field = page.getByPlaceholder(/Ask something/);
  await field.fill("before\nafter");
  await field.press("Control+Home");
  await field.pressSequentially("- ");
  const editor = page.locator(".list-composer");
  await expect(editor).toBeVisible();
  await editor.pressSequentially("insert ");
  await expect(editor.locator("li")).toHaveText("insert before");
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toBe("- insert before\n\nafter");
});

test("typing list-looking examples inside code fences stays literal", async ({ page }) => {
  const api = await installFakeApi(page);
  await logIn(page);
  await page.getByPlaceholder(/Ask something/).fill("- first");
  const editor = page.locator(".list-composer");
  await editor.press("Shift+Enter");
  await editor.press("Shift+Enter");
  await editor.pressSequentially("```");
  await editor.press("Shift+Enter");
  await editor.pressSequentially("- literal");
  await expect(editor.locator("ul > li")).toHaveCount(1);
  await expect(editor.locator(":scope > p").last()).toHaveText("- literal");
  await editor.press("Enter");
  await expect.poll(() => api.turns.length).toBe(1);
  expect(api.turns[0]!.question).toContain("```\n- literal");
});
