import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attachmentsClient } from "../api/AttachmentsClient";
import type { PromptTemplate } from "../api/TemplatesClient";
import { withAttachments } from "../utils/attachments";
import ChatInput from "./ChatInput.vue";
import inputSource from "./ChatInput.vue?raw";
import menuSource from "./ChatSettingsMenu.vue?raw";

vi.mock("../api/AttachmentsClient", () => ({ attachmentsClient: { text: vi.fn(), table: vi.fn() } }));

const text = vi.mocked(attachmentsClient.text);
const table = vi.mocked(attachmentsClient.table);

function mountInput(props: Record<string, unknown> = {}) {
  return mount(ChatInput, { props: { busy: false, ...props }, attachTo: document.body });
}

const file = (name = "shot.png") => new File(["x"], name);

/** A clipboard as the paste event sees it. */
const clipboard = (files: File[], plain = "") => ({ files, getData: (type: string) => (type === "text/plain" ? plain : "") });

/** A drag as the drag events see it. */
const drag = (types: string[], files: File[] = []) => ({ types, files });

beforeEach(() => {
  text.mockResolvedValue({ text: "extracted", char_count: 9, truncated: false } as never);
  table.mockResolvedValue({ table_id: "tbl-1", filename: "sales.csv", rows: 1200, columns: ["region", "units"], sheet: null, notes: [] });
});

afterEach(() => {
  document.body.innerHTML = "";
});

describe("giving back a question that was not taken", () => {
  it("puts the typed text and its files back into an empty box", async () => {
    const wrapper = mountInput();
    const question = withAttachments("Summarise this", [{ filename: "notes.txt", chars: 5, truncated: false, text: "hello" }]);

    (wrapper.vm as unknown as { restore: (q: string) => void }).restore(question);
    await flushPromises();

    expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe("Summarise this");
    expect(wrapper.find(".attachments li").text()).toContain("notes.txt");
    await wrapper.find("form").trigger("submit");
    expect(wrapper.emitted("send")![0]).toEqual([question]);
  });

  it("never overwrites what was typed since", async () => {
    const wrapper = mountInput();
    await wrapper.find("textarea").setValue("something new");

    (wrapper.vm as unknown as { restore: (q: string) => void }).restore("old question");
    await flushPromises();

    expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe("something new");
  });

  it("leaves the box empty after a send that was taken (nothing is restored unasked)", async () => {
    const wrapper = mountInput();
    await wrapper.find("textarea").setValue("a question");

    await wrapper.find("form").trigger("submit");

    expect(wrapper.emitted("send")![0]).toEqual(["a question"]);
    expect((wrapper.find("textarea").element as HTMLTextAreaElement).value).toBe("");
  });
});

describe("pasting files", () => {
  it("turns a pasted file into an attachment and keeps it out of the text", async () => {
    const wrapper = mountInput();
    const pasted = file("screenshot.png");

    const textarea = wrapper.find("textarea");
    await textarea.trigger("paste", { clipboardData: clipboard([pasted]) });
    await flushPromises();

    expect(text).toHaveBeenCalledExactlyOnceWith(pasted);
    expect(wrapper.find(".attachments li").text()).toContain("screenshot.png");
    expect((textarea.element as HTMLTextAreaElement).value).toBe("");
  });

  it("prevents the browser's own paste when it took the files", async () => {
    const wrapper = mountInput();
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.assign(event, { clipboardData: clipboard([file()]) });

    wrapper.find("textarea").element.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves text alone, even when the clipboard also holds an image (spreadsheet cells)", async () => {
    const wrapper = mountInput();
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.assign(event, { clipboardData: clipboard([file()], "a\tb\n1\t2") });

    wrapper.find("textarea").element.dispatchEvent(event);
    await flushPromises();

    expect(event.defaultPrevented).toBe(false);
    expect(text).not.toHaveBeenCalled();
    expect(wrapper.find(".attachments").exists()).toBe(false);
  });

  it("ignores a paste with no files and no clipboard data", async () => {
    const wrapper = mountInput();

    await wrapper.find("textarea").trigger("paste", { clipboardData: clipboard([]) });
    await wrapper.find("textarea").trigger("paste");

    expect(text).not.toHaveBeenCalled();
  });

  it("shows a file ember_api could not read as an error chip", async () => {
    text.mockRejectedValue(new Error("Unsupported file type"));
    const wrapper = mountInput();

    await wrapper.find("textarea").trigger("paste", { clipboardData: clipboard([file("pic.png")]) });
    await flushPromises();

    const chip = wrapper.find(".attachments li");
    expect(chip.classes()).toContain("error");
    expect(chip.text()).toContain("Unsupported file type");
  });
});

describe("attaching a table", () => {
  it("uploads a .csv beside reading its text and puts the table id in the sent question", async () => {
    const wrapper = mountInput();
    const sheet = file("sales.csv");

    await wrapper.find("form").trigger("drop", { dataTransfer: drag(["Files"], [sheet]) });
    await flushPromises();

    expect(text).toHaveBeenCalledExactlyOnceWith(sheet);
    expect(table).toHaveBeenCalledExactlyOnceWith(sheet);
    expect(wrapper.find(".attachments li").text()).toContain("1,200 rows, 2 columns");
    await wrapper.find("textarea").setValue("total units per region?");
    await wrapper.find("form").trigger("submit");
    const sent = wrapper.emitted("send")![0]![0] as string;
    expect(sent).toContain("table_id: tbl-1");
    expect(sent).toContain("extracted");
  });

  it("does not upload other files as tables", async () => {
    const wrapper = mountInput();

    await wrapper.find("form").trigger("drop", { dataTransfer: drag(["Files"], [file("notes.txt")]) });
    await flushPromises();

    expect(table).not.toHaveBeenCalled();
  });

  it("still attaches the preview, and says so, when the table upload fails", async () => {
    table.mockRejectedValue(new Error("mcp_server is unreachable"));
    const wrapper = mountInput();

    await wrapper.find("form").trigger("drop", { dataTransfer: drag(["Files"], [file("sales.xlsx")]) });
    await flushPromises();

    expect(wrapper.find(".attachments li").classes()).not.toContain("error");
    await wrapper.find("textarea").setValue("summarise");
    await wrapper.find("form").trigger("submit");
    expect(wrapper.emitted("send")![0]![0] as string).toContain("could not be loaded");
  });
});

describe("dropping files anywhere on the composer", () => {
  it("attaches files dropped on the form, not just on the input box", async () => {
    const wrapper = mountInput();
    const dropped = file("notes.txt");

    await wrapper.find("form").trigger("drop", { dataTransfer: drag(["Files"], [dropped]) });
    await flushPromises();

    expect(text).toHaveBeenCalledExactlyOnceWith(dropped);
  });

  it("highlights the box while files are dragged over, and stops when they leave", async () => {
    const wrapper = mountInput();
    const form = wrapper.find("form");

    await form.trigger("dragover", { dataTransfer: drag(["Files"]) });
    expect(wrapper.find(".box").classes()).toContain("dragging");

    await form.trigger("dragleave", { relatedTarget: null });
    expect(wrapper.find(".box").classes()).not.toContain("dragging");
  });

  it("keeps the highlight when the drag only moves onto a child element", async () => {
    const wrapper = mountInput();
    const form = wrapper.find("form");
    await form.trigger("dragover", { dataTransfer: drag(["Files"]) });

    await form.trigger("dragleave", { relatedTarget: wrapper.find("textarea").element });

    expect(wrapper.find(".box").classes()).toContain("dragging");
  });

  it("leaves dragged text alone", async () => {
    const wrapper = mountInput();
    const over = new Event("dragover", { bubbles: true, cancelable: true });
    Object.assign(over, { dataTransfer: drag(["text/plain"]) });
    const drop = new Event("drop", { bubbles: true, cancelable: true });
    Object.assign(drop, { dataTransfer: drag(["text/plain"]) });

    wrapper.find("form").element.dispatchEvent(over);
    wrapper.find("form").element.dispatchEvent(drop);

    expect(over.defaultPrevented).toBe(false);
    expect(drop.defaultPrevented).toBe(false);
    expect(wrapper.find(".box").classes()).not.toContain("dragging");
    expect(text).not.toHaveBeenCalled();
  });
});

describe("Up and Down walk through the questions asked before", () => {
  const textareaOf = (wrapper: ReturnType<typeof mountInput>) => wrapper.find("textarea").element as HTMLTextAreaElement;
  const press = (wrapper: ReturnType<typeof mountInput>, key: string) => wrapper.find("textarea").trigger("keydown", { key });
  const HISTORY = ["first", "second", "third"];
  const badge = (wrapper: ReturnType<typeof mountInput>) => wrapper.find(".recall");

  it("Up in an empty box brings back the newest question", async () => {
    const wrapper = mountInput({ history: HISTORY });

    await press(wrapper, "ArrowUp");

    expect(textareaOf(wrapper).value).toBe("third");
    expect(badge(wrapper).text()).toContain("3 of 3");
  });

  it("each further Up goes one question older and stops at the oldest", async () => {
    const wrapper = mountInput({ history: HISTORY });

    await press(wrapper, "ArrowUp");
    await press(wrapper, "ArrowUp");
    expect(textareaOf(wrapper).value).toBe("second");
    await press(wrapper, "ArrowUp");
    await press(wrapper, "ArrowUp");

    expect(textareaOf(wrapper).value).toBe("first");
    expect(badge(wrapper).text()).toContain("1 of 3");
  });

  it("Down goes newer again, and past the newest empties the box", async () => {
    const wrapper = mountInput({ history: HISTORY });
    await press(wrapper, "ArrowUp");
    await press(wrapper, "ArrowUp");

    await press(wrapper, "ArrowDown");
    expect(textareaOf(wrapper).value).toBe("third");

    await press(wrapper, "ArrowDown");
    expect(textareaOf(wrapper).value).toBe("");
    expect(badge(wrapper).exists()).toBe(false);
  });

  it("keeps the browser from also moving the caret when it takes a key", async () => {
    const wrapper = mountInput({ history: HISTORY });
    const up = new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true });
    wrapper.find("textarea").element.dispatchEvent(up);
    await flushPromises();
    const down = new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });
    wrapper.find("textarea").element.dispatchEvent(down);

    expect(up.defaultPrevented).toBe(true);
    expect(down.defaultPrevented).toBe(true);
  });

  it("Down does nothing when not browsing", async () => {
    const wrapper = mountInput({ history: HISTORY });
    const event = new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });

    wrapper.find("textarea").element.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
    expect(textareaOf(wrapper).value).toBe("");
  });

  it("never overwrites what is being typed", async () => {
    const wrapper = mountInput({ history: HISTORY });
    await wrapper.find("textarea").setValue("draft");

    await press(wrapper, "ArrowUp");

    expect(textareaOf(wrapper).value).toBe("draft");
    expect(badge(wrapper).exists()).toBe(false);
  });

  it("does nothing when there are no questions yet", async () => {
    const wrapper = mountInput({ history: [] });

    const event = new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true });
    wrapper.find("textarea").element.dispatchEvent(event);

    expect(textareaOf(wrapper).value).toBe("");
    expect(event.defaultPrevented).toBe(false);
  });

  it("typing over a recalled question ends browsing, so Up no longer replaces it", async () => {
    const wrapper = mountInput({ history: HISTORY });
    await press(wrapper, "ArrowUp");

    await wrapper.find("textarea").setValue("third, edited");
    await press(wrapper, "ArrowUp");

    expect(textareaOf(wrapper).value).toBe("third, edited");
    expect(badge(wrapper).exists()).toBe(false);
  });

  it("lets the arrows move the caret inside a multi-line question first", async () => {
    const wrapper = mountInput({ history: ["one", "line a\nline b"] });
    await press(wrapper, "ArrowUp");
    const el = textareaOf(wrapper);

    el.setSelectionRange(10, 10); // on the second line
    const middle = new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true });
    el.dispatchEvent(middle);
    expect(middle.defaultPrevented).toBe(false);
    expect(el.value).toBe("line a\nline b");

    el.setSelectionRange(2, 2); // on the first line
    await press(wrapper, "ArrowUp");
    expect(el.value).toBe("one");
  });

  it("Down moves on only from the last line", async () => {
    const wrapper = mountInput({ history: ["line a\nline b", "last"] });
    await press(wrapper, "ArrowUp");
    await press(wrapper, "ArrowUp");
    const el = textareaOf(wrapper);

    el.setSelectionRange(2, 2); // first line: Down belongs to the caret
    const early = new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true, cancelable: true });
    el.dispatchEvent(early);
    expect(early.defaultPrevented).toBe(false);
    expect(el.value).toBe("line a\nline b");

    el.setSelectionRange(el.value.length, el.value.length);
    await press(wrapper, "ArrowDown");
    expect(el.value).toBe("last");
  });

  it("starts over when the questions change (another chat)", async () => {
    const wrapper = mountInput({ history: HISTORY });
    await press(wrapper, "ArrowUp");
    expect(badge(wrapper).exists()).toBe(true);

    await wrapper.setProps({ history: ["elsewhere"] });

    expect(badge(wrapper).exists()).toBe(false);
  });

  it("keeps browsing when the same questions arrive again", async () => {
    const wrapper = mountInput({ history: HISTORY });
    await press(wrapper, "ArrowUp");

    await wrapper.setProps({ history: [...HISTORY] });

    expect(badge(wrapper).exists()).toBe(true);
  });

  it("does not browse while an IME is composing", async () => {
    const wrapper = mountInput({ history: HISTORY });
    const event = new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true });
    Object.defineProperty(event, "isComposing", { value: true });

    wrapper.find("textarea").element.dispatchEvent(event);

    expect(textareaOf(wrapper).value).toBe("");
    expect(event.defaultPrevented).toBe(false);
  });

  it("sends the recalled question when Enter follows, and stops browsing", async () => {
    const wrapper = mountInput({ history: ["again please"] });
    await press(wrapper, "ArrowUp");

    await press(wrapper, "Enter");

    expect(wrapper.emitted("send")).toEqual([["again please"]]);
    expect(badge(wrapper).exists()).toBe(false);
  });
});

describe("the rest of the composer", () => {
  it("Enter sends, Shift+Enter does not", async () => {
    const wrapper = mountInput();
    await wrapper.find("textarea").setValue("hello");

    await wrapper.find("textarea").trigger("keydown", { key: "Enter", shiftKey: true });
    expect(wrapper.emitted("send")).toBeUndefined();

    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("send")).toEqual([["hello"]]);
  });

  it("shows Stop (Esc) while an answer runs, and emits stop", async () => {
    const wrapper = mountInput({ busy: true });
    const stop = wrapper.find("button.stop");

    expect(stop.attributes("title")).toBe("Stop (Esc)");
    await stop.trigger("click");

    expect(wrapper.emitted("stop")).toHaveLength(1);
  });

  it("focus() puts the caret in the box (Ctrl+K)", () => {
    const wrapper = mountInput();

    (wrapper.vm as unknown as { focus: () => void }).focus();

    expect(document.activeElement).toBe(wrapper.find("textarea").element);
  });
});

describe("saved prompts", () => {
  const tpl = (id: number, name: string, body: string): PromptTemplate => ({
    id,
    name,
    body,
    created_at: "2026-01-01T00:00:00",
    updated_at: "2026-01-01T00:00:00",
  });
  const TEMPLATES = [tpl(1, "Summarize", "Summarize this:"), tpl(2, "Code review", "Review this code:\n"), tpl(3, "Review notes", "Turn my notes into a review")];
  const valueOf = (wrapper: ReturnType<typeof mountInput>) => (wrapper.find("textarea").element as HTMLTextAreaElement).value;
  const rows = (wrapper: ReturnType<typeof mountInput>) => wrapper.findAll(".suggestions li[role=option] code").map((c) => c.text());

  it("typing # lists the prompts, filtering by name as you continue", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });

    await wrapper.find("textarea").setValue("#");
    expect(rows(wrapper)).toEqual(["Summarize", "Code review", "Review notes"]);

    await wrapper.find("textarea").setValue("#review");
    expect(rows(wrapper)).toEqual(["Review notes", "Code review"]);
    expect(wrapper.find(".hint").text()).toBe("Tab or Enter inserts the prompt");
  });

  it("asks the parent to load the prompts when # is typed, once per lookup", async () => {
    const wrapper = mountInput();

    await wrapper.find("textarea").setValue("hello");
    expect(wrapper.emitted("templatesNeeded")).toBeUndefined();

    await wrapper.find("textarea").setValue("#");
    await wrapper.find("textarea").setValue("#r");
    expect(wrapper.emitted("templatesNeeded")).toHaveLength(1);

    await wrapper.find("textarea").setValue("");
    await wrapper.find("textarea").setValue("#");
    expect(wrapper.emitted("templatesNeeded")).toHaveLength(2);
  });

  it("Tab puts the highlighted prompt's text in the box", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });
    await wrapper.find("textarea").setValue("#sum");

    await wrapper.find("textarea").trigger("keydown", { key: "Tab" });

    expect(valueOf(wrapper)).toBe("Summarize this:");
    expect(wrapper.find(".suggestions").exists()).toBe(false);
    expect(wrapper.emitted("send")).toBeUndefined();
  });

  it("Enter inserts the prompt instead of sending '#sum'", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });
    await wrapper.find("textarea").setValue("#sum");

    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });

    expect(valueOf(wrapper)).toBe("Summarize this:");
    expect(wrapper.emitted("send")).toBeUndefined();
  });

  it("arrow keys move the highlight before Enter", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });
    await wrapper.find("textarea").setValue("#");

    await wrapper.find("textarea").trigger("keydown", { key: "ArrowDown" });
    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });

    expect(valueOf(wrapper)).toBe("Review this code:\n");
  });

  it("a click on a suggestion inserts it", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });
    await wrapper.find("textarea").setValue("#");

    await wrapper.findAll(".suggestions li[role=option]")[2]!.trigger("mousedown");

    expect(valueOf(wrapper)).toBe("Turn my notes into a review");
  });

  it("with no match, # is just text and Enter sends it", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });
    await wrapper.find("textarea").setValue("#1 thing to fix");

    expect(wrapper.find(".suggestions").exists()).toBe(false);
    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("send")).toEqual([["#1 thing to fix"]]);
  });

  it("# in the middle of a message does nothing", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });

    await wrapper.find("textarea").setValue("see issue #12");

    expect(wrapper.find(".suggestions").exists()).toBe(false);
  });

  it("slash commands keep their own suggestions and hint", async () => {
    const wrapper = mountInput({
      templates: TEMPLATES,
      commands: [{ capability: "apps", name: "start", description: "Start an app", tool_name: "t" }],
    });

    await wrapper.find("textarea").setValue("/apps");

    expect(rows(wrapper)).toEqual(["/apps help", "/apps start"]);
    expect(wrapper.find(".hint").text()).toContain("Enter runs");
  });

  it("offers the built-in commands, even with no tools loaded", async () => {
    const wrapper = mountInput();

    await wrapper.find("textarea").setValue("/");
    expect(rows(wrapper)).toEqual(["/clear", "/compact", "/export", "/share"]);

    await wrapper.find("textarea").setValue("/co");
    expect(rows(wrapper)).toEqual(["/compact"]);
  });

  it("lists the built-ins before /help and the capabilities", async () => {
    const wrapper = mountInput({ commands: [{ capability: "cal", name: "now", description: "Time", tool_name: "t" }] });

    await wrapper.find("textarea").setValue("/");

    expect(rows(wrapper).slice(0, 5)).toEqual(["/clear", "/compact", "/export", "/share", "/help"]);
  });

  it("picking a built-in puts it in the box, and Enter sends it", async () => {
    const wrapper = mountInput();
    await wrapper.find("textarea").setValue("/exp");

    await wrapper.find("textarea").trigger("keydown", { key: "Tab" });
    expect(valueOf(wrapper)).toBe("/export ");

    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("send")).toEqual([["/export"]]);
  });

  it("keeps the highlighted suggestion in view when the arrows move it", async () => {
    const wrapper = mountInput({
      templates: TEMPLATES,
      commands: [{ capability: "apps", name: "start", description: "Start an app", tool_name: "t" }],
    });
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;

    await wrapper.find("textarea").setValue("/apps");
    await wrapper.find("textarea").trigger("keydown", { key: "ArrowDown" });
    await flushPromises();

    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("sits above the chat settings menu", () => {
    const css = inputSource;
    const menu = menuSource;
    const z =(source: string, selector: string) =>
      Number(new RegExp(`${selector}\\s*\\{[^}]*z-index:\\s*(\\d+)`).exec(source)![1]);

    expect(z(css, "\\.suggestions")).toBeGreaterThan(z(menu, "\\.settings-menu"));
  });

  describe("a command's parameters", () => {
    const COMMAND = { capability: "apps", name: "start", description: "Start an app", tool_name: "apps_start" };
    const SCHEMA = {
      type: "object",
      required: ["name"],
      properties: {
        name: { type: "string", description: "App to start", examples: ["web", "api"] },
        mode: { type: "string", enum: ["fast", "slow"] },
        verbose: { type: "boolean" },
      },
    };

    async function typing(value: string) {
      const schemaFor = vi.fn().mockResolvedValue(SCHEMA);
      const wrapper = mountInput({ commands: [COMMAND], schemaFor });
      await wrapper.find("textarea").setValue(value);
      await flushPromises();
      return { wrapper, schemaFor };
    }

    it("suggests the parameters once the command is typed", async () => {
      const { wrapper, schemaFor } = await typing("/apps start ");

      expect(schemaFor).toHaveBeenCalledWith(COMMAND);
      expect(rows(wrapper)).toEqual(["name=", "mode=", "verbose="]);
      expect(wrapper.find("li[role=option] span").text()).toBe("required · App to start");
    });

    it("leaves out parameters already given", async () => {
      const { wrapper } = await typing("/apps start name=web m");

      expect(rows(wrapper)).toEqual(["mode="]);
    });

    it("suggests a parameter's choices, examples or true/false after its =", async () => {
      expect(rows((await typing("/apps start mode=")).wrapper)).toEqual(["mode=fast", "mode=slow"]);
      expect(rows((await typing("/apps start name=w")).wrapper)).toEqual(["name=web"]);
      expect(rows((await typing("/apps start verbose=")).wrapper)).toEqual(["verbose=true", "verbose=false"]);
    });

    it("Tab completes only the word being typed", async () => {
      const { wrapper } = await typing("/apps start name=web mo");

      await wrapper.find("textarea").trigger("keydown", { key: "Tab" });

      expect(valueOf(wrapper)).toBe("/apps start name=web mode=");
    });

    it("Tab after a value ends the word with a space", async () => {
      const { wrapper } = await typing("/apps start mode=sl");

      await wrapper.find("textarea").trigger("keydown", { key: "Tab" });

      expect(valueOf(wrapper)).toBe("/apps start mode=slow ");
    });

    it("suggests nothing inside an open quote or for a tool without parameters", async () => {
      expect(rows((await typing('/apps start name="a ')).wrapper)).toEqual([]);
      const schemaFor = vi.fn().mockResolvedValue(null);
      const wrapper = mountInput({ commands: [COMMAND], schemaFor });
      await wrapper.find("textarea").setValue("/apps start ");
      await flushPromises();
      expect(wrapper.find(".suggestions").exists()).toBe(false);
    });
  });

  it("the picker button inserts a prompt into an empty box, or after typed text on a new line", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });

    await wrapper.find("button.trigger").trigger("click");
    await wrapper.findAll(".picker .item")[0]!.trigger("click");
    expect(valueOf(wrapper)).toBe("Summarize this:");

    await wrapper.find("textarea").setValue("Here is my text");
    await wrapper.find("button.trigger").trigger("click");
    await wrapper.findAll(".picker .item")[0]!.trigger("click");
    expect(valueOf(wrapper)).toBe("Here is my text\nSummarize this:");
  });

  it("opening the picker asks the parent to load the prompts", async () => {
    const wrapper = mountInput();

    await wrapper.find("button.trigger").trigger("click");

    expect(wrapper.emitted("templatesNeeded")).toHaveLength(1);
  });

  it("Manage opens the dialog with no draft; Save current text offers what is typed", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });

    await wrapper.find("button.trigger").trigger("click");
    await wrapper.findAll(".picker .foot button")[1]!.trigger("click"); // Manage
    expect(wrapper.emitted("manageTemplates")).toEqual([[""]]);

    await wrapper.find("textarea").setValue("  a prompt I keep retyping  ");
    await wrapper.find("button.trigger").trigger("click");
    await wrapper.findAll(".picker .foot button")[0]!.trigger("click"); // Save current text
    expect(wrapper.emitted("manageTemplates")![1]).toEqual(["a prompt I keep retyping"]);
  });

  it("Save current text is off while the box is empty", async () => {
    const wrapper = mountInput({ templates: TEMPLATES });

    await wrapper.find("button.trigger").trigger("click");

    expect(wrapper.findAll(".picker .foot button")[0]!.attributes("disabled")).toBeDefined();
  });

  it("insertText() is what the parent can call to add text", async () => {
    const wrapper = mountInput();
    await wrapper.find("textarea").setValue("first");

    (wrapper.vm as unknown as { insertText: (text: string) => void }).insertText("second");
    await flushPromises();

    expect(valueOf(wrapper)).toBe("first\nsecond");
  });
});

describe("the tools row", () => {
  it("holds attach, saved prompts, the page's own controls and Send under the text box", () => {
    const wrapper = mount(ChatInput, {
      props: { busy: false },
      slots: { tools: '<span class="page-control">Settings</span>' },
      attachTo: document.body,
    });

    const row = wrapper.get(".box .tools");
    expect(row.element.previousElementSibling).toBe(wrapper.get("textarea").element);
    expect(row.find(".attach").exists()).toBe(true);
    expect(row.find(".picker").exists()).toBe(true);
    expect(row.find(".page-control").text()).toBe("Settings");
    expect(row.find("button.send").exists()).toBe(true);
  });

  it("swaps Send for Stop in the same row while an answer is being written", () => {
    const wrapper = mountInput({ busy: true });

    expect(wrapper.find(".tools button.stop").exists()).toBe(true);
    expect(wrapper.find("button.send").exists()).toBe(false);
  });
});
