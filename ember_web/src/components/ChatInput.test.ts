import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { attachmentsClient } from "../api/AttachmentsClient";
import ChatInput from "./ChatInput.vue";

vi.mock("../api/AttachmentsClient", () => ({ attachmentsClient: { text: vi.fn() } }));

const text = vi.mocked(attachmentsClient.text);

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
});

afterEach(() => {
  document.body.innerHTML = "";
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

describe("Up recalls the last question", () => {
  const textareaOf = (wrapper: ReturnType<typeof mountInput>) => wrapper.find("textarea").element as HTMLTextAreaElement;

  it("fills an empty input", async () => {
    const wrapper = mountInput({ lastPrompt: "what is up" });

    await wrapper.find("textarea").trigger("keydown", { key: "ArrowUp" });

    expect(textareaOf(wrapper).value).toBe("what is up");
  });

  it("never overwrites what is being typed", async () => {
    const wrapper = mountInput({ lastPrompt: "old" });
    await wrapper.find("textarea").setValue("draft");

    await wrapper.find("textarea").trigger("keydown", { key: "ArrowUp" });

    expect(textareaOf(wrapper).value).toBe("draft");
  });

  it("does nothing when there is no last question", async () => {
    const wrapper = mountInput({ lastPrompt: "" });

    const event = new KeyboardEvent("keydown", { key: "ArrowUp", bubbles: true, cancelable: true });
    wrapper.find("textarea").element.dispatchEvent(event);

    expect(textareaOf(wrapper).value).toBe("");
    expect(event.defaultPrevented).toBe(false);
  });

  it("sends the recalled question when Enter follows", async () => {
    const wrapper = mountInput({ lastPrompt: "again please" });
    await wrapper.find("textarea").trigger("keydown", { key: "ArrowUp" });

    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });

    expect(wrapper.emitted("send")).toEqual([["again please"]]);
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
