import { flushPromises, mount, type DOMWrapper } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../api/types";
import { withAttachments } from "../utils/attachments";
import MessageList from "./MessageList.vue";

const user = (content: string): ChatMessage => ({ role: "user", content });
const assistant = (content: string, extra: Partial<ChatMessage> = {}): ChatMessage => ({
  role: "assistant",
  content,
  ...extra,
});

const FOUR = [user("q1"), assistant("a1"), user("q2"), assistant("a2")];
const FILE = { filename: "f.txt", chars: 3, truncated: false, text: "abc" };

type Props = InstanceType<typeof MessageList>["$props"];

function mountList(props: Partial<Props> = {}) {
  return mount(MessageList, {
    props: { messages: FOUR, streaming: "", activity: "", steps: [], busy: false, canChange: true, regenerateIndex: 2, ...props },
    attachTo: document.body,
  });
}

// jsdom doesn't lay anything out and has no scrollIntoView.
let scrollIntoView: ReturnType<typeof vi.fn>;
beforeEach(() => {
  scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView as unknown as Element["scrollIntoView"];
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("jumping to a message (a search result)", () => {
  it("scrolls the message to the centre, flashes it, then says it is done", async () => {
    vi.useFakeTimers();
    const wrapper = mountList({ jumpIndex: 2 });
    await vi.advanceTimersByTimeAsync(0);

    expect(scrollIntoView).toHaveBeenCalledExactlyOnceWith({ block: "center" });
    const target = scrollIntoView.mock.contexts[0] as HTMLElement;
    expect(target.dataset.index).toBe("2");
    expect(wrapper.findAll(".msg")[2]!.classes()).toContain("flash");
    expect(wrapper.emitted("jumped")).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(1600);
    expect(wrapper.find(".flash").exists()).toBe(false);
  });

  it("follows a target set after the list is already showing", async () => {
    const wrapper = mountList();
    await flushPromises();
    expect(scrollIntoView).not.toHaveBeenCalled();

    await wrapper.setProps({ jumpIndex: 0 });
    await flushPromises();

    expect((scrollIntoView.mock.contexts[0] as HTMLElement).dataset.index).toBe("0");
  });

  it("drops a target past the end of the chat without scrolling", async () => {
    const wrapper = mountList({ jumpIndex: 9 });
    await flushPromises();

    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(wrapper.emitted("jumped")).toHaveLength(1);
  });

  it("treats the first index past the end as out of range, and the last message as in range", async () => {
    const past = mountList({ jumpIndex: FOUR.length });
    await flushPromises();
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(past.emitted("jumped")).toHaveLength(1);

    const last = mountList({ jumpIndex: FOUR.length - 1 });
    await flushPromises();
    expect((scrollIntoView.mock.contexts[0] as HTMLElement).dataset.index).toBe("3");
    expect(last.emitted("jumped")).toHaveLength(1);
  });

  it("does nothing without a target", async () => {
    const wrapper = mountList({ jumpIndex: null });
    await flushPromises();

    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(wrapper.emitted("jumped")).toBeUndefined();
  });

  it("wraps every message once, in order, with its index", () => {
    const wrapper = mountList();

    expect(wrapper.findAll(".msg").map((m) => m.attributes("data-index"))).toEqual(["0", "1", "2", "3"]);
  });
});

describe("regenerate button", () => {
  it("appears on the last answer only, and emits regenerate", async () => {
    const wrapper = mountList();
    const buttons = wrapper.findAll('button[aria-label="Regenerate answer"]');

    expect(buttons).toHaveLength(1);
    expect(wrapper.findAll(".msg")[3]!.find('button[aria-label="Regenerate answer"]').exists()).toBe(true);

    await buttons[0]!.trigger("click");
    expect(wrapper.emitted("regenerate")).toHaveLength(1);
  });

  it.each([
    ["nothing to redo", { regenerateIndex: -1 }],
    ["an answer is running", { canChange: false }],
    ["the parent gave no index", { regenerateIndex: undefined }],
  ])("is hidden when %s", (_name, props) => {
    const wrapper = mountList(props);

    expect(wrapper.find('button[aria-label="Regenerate answer"]').exists()).toBe(false);
  });
});

describe("editing a question", () => {
  const editButtons = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll('button[aria-label="Edit and resend"]');

  it("offers an edit on every typed question, not on answers", () => {
    expect(editButtons(mountList())).toHaveLength(2);
  });

  it("is not offered while an answer is running", () => {
    expect(editButtons(mountList({ canChange: false }))).toHaveLength(0);
  });

  it("opens with the typed text, and Save & resend emits the new text", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[0]!.trigger("click");
    const area = wrapper.find("textarea");

    expect((area.element as HTMLTextAreaElement).value).toBe("q1");
    await area.setValue("q1 edited");
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await wrapper.find("button.primary").trigger("click");

    expect(wrapper.emitted("edit")).toEqual([[0, "q1 edited"]]);
    expect(wrapper.find("textarea").exists()).toBe(false);
  });

  it("asks before discarding later exchanges, and stays open on 'no'", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const wrapper = mountList();
    await editButtons(wrapper)[0]!.trigger("click"); // q1 has q2 after it
    await wrapper.find("textarea").setValue("changed");

    await wrapper.find("button.primary").trigger("click");

    expect(confirm).toHaveBeenCalledOnce();
    expect(wrapper.emitted("edit")).toBeUndefined();
    expect(wrapper.find("textarea").exists()).toBe(true);
  });

  it("does not ask when editing the last question", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const wrapper = mountList();
    await editButtons(wrapper)[1]!.trigger("click"); // q2 is the last
    await wrapper.find("textarea").setValue("q2 edited");

    await wrapper.find("button.primary").trigger("click");

    expect(confirm).not.toHaveBeenCalled();
    expect(wrapper.emitted("edit")).toEqual([[2, "q2 edited"]]);
  });

  it("Enter saves, Shift+Enter does not, Esc cancels", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const wrapper = mountList();
    await editButtons(wrapper)[1]!.trigger("click");
    const area = wrapper.find("textarea");
    await area.setValue("again");

    await area.trigger("keydown", { key: "Enter", shiftKey: true });
    expect(wrapper.emitted("edit")).toBeUndefined();

    await area.trigger("keydown", { key: "Escape" });
    expect(wrapper.find("textarea").exists()).toBe(false);
    expect(wrapper.emitted("edit")).toBeUndefined();

    await editButtons(wrapper)[1]!.trigger("click");
    await wrapper.find("textarea").setValue("again");
    await wrapper.find("textarea").trigger("keydown", { key: "Enter" });
    expect(wrapper.emitted("edit")).toEqual([[2, "again"]]);
  });

  it("will not save a blank question, but will for one that has a file", async () => {
    const wrapper = mountList({
      messages: [user("plain"), assistant("a"), user(withAttachments("with file", [FILE])), assistant("b")],
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    await editButtons(wrapper)[0]!.trigger("click");
    await wrapper.find("textarea").setValue("   ");
    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.emitted("edit")).toBeUndefined();
    await wrapper.find("button.ghost").trigger("click");

    await editButtons(wrapper)[1]!.trigger("click");
    expect(wrapper.find(".edit-note").text()).toContain("Attached files stay");
    await wrapper.find("textarea").setValue("");
    await wrapper.find("button.primary").trigger("click");
    expect(wrapper.emitted("edit")).toEqual([[2, ""]]);
  });

  it("closes the editor when an answer starts running", async () => {
    const wrapper = mountList();
    await editButtons(wrapper)[0]!.trigger("click");
    expect(wrapper.find("textarea").exists()).toBe(true);

    await wrapper.setProps({ busy: true, canChange: false });

    expect(wrapper.find("textarea").exists()).toBe(false);
  });
});

describe("copy buttons", () => {
  it("are on questions and answers; a question shows its typed text apart from its file", () => {
    const wrapper = mountList({ messages: [user(withAttachments("look at this", [FILE])), assistant("ok")] });

    const labels = wrapper
      .findAll('button[aria-label="Copy message"], button[aria-label="Copy answer"]')
      .map((b) => b.attributes("aria-label"));

    expect(labels).toEqual(["Copy message", "Copy answer"]);
    expect(wrapper.find(".user-bubble").text()).toContain("look at this");
  });
});

describe("branch button", () => {
  const branchButtons = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll('button[aria-label="Branch from this answer"]');

  it("is on every answer, not on questions, and emits the answer's index", async () => {
    const wrapper = mountList();
    const buttons = branchButtons(wrapper);

    expect(buttons).toHaveLength(2);
    expect(wrapper.findAll(".msg")[0]!.find('button[aria-label="Branch from this answer"]').exists()).toBe(false);

    await buttons[0]!.trigger("click");
    await buttons[1]!.trigger("click");
    expect(wrapper.emitted("branch")).toEqual([[1], [3]]);
  });

  it("is hidden while an answer is running or another change is under way", () => {
    expect(branchButtons(mountList({ canChange: false }))).toHaveLength(0);
  });

  it("is not on summaries, raw logs or command results", () => {
    const wrapper = mountList({
      messages: [
        assistant("S", { kind: "summary" }),
        assistant("raw", { kind: "log_attachment" }),
        { role: "user", content: "/x y", kind: "command" },
        assistant("result", { kind: "command" }),
        user("q"),
        assistant("a"),
      ],
      regenerateIndex: 4,
    });

    expect(branchButtons(wrapper)).toHaveLength(1);
    expect(wrapper.findAll(".msg")[5]!.find('button[aria-label="Branch from this answer"]').exists()).toBe(true);
  });

  it("sits beside the regenerate button on the last answer", () => {
    const wrapper = mountList();

    const labels = wrapper.findAll(".msg")[3]!.findAll(".actions button").map((b) => b.attributes("aria-label"));

    expect(labels).toContain("Regenerate answer");
    expect(labels).toContain("Branch from this answer");
  });
});

describe("tool approval cards", () => {
  const STOP_APP = { id: "step0", tool: "tool_srv_stopApp", label: "", arguments: { app: "web", force: true } };
  const cards = (wrapper: ReturnType<typeof mountList>) => wrapper.findAll(".approval");
  const buttons = (card: DOMWrapper<Element>) => card.findAll(".buttons button");

  it("shows nothing when no tool is waiting", () => {
    expect(cards(mountList({ busy: true, approvals: [] })).length).toBe(0);
    expect(cards(mountList({ busy: true })).length).toBe(0);
  });

  it("shows a card for each waiting tool while the answer is being written", () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP, { ...STOP_APP, id: "step1", tool: "tool_srv_startApp" }] });

    expect(cards(wrapper)).toHaveLength(2);
    expect(cards(wrapper)[0]!.find("header strong").text()).toBe("Stop App");
    expect(cards(wrapper)[1]!.find("header strong").text()).toBe("Start App");
    expect(cards(wrapper)[0]!.find("header code").text()).toBe("tool_srv_stopApp");
    expect(cards(wrapper)[0]!.text()).toContain("will not run until you allow it");
    expect(cards(wrapper)[0]!.text()).toContain("counts as Deny");
  });

  it("uses the tool's own display label when it has one", () => {
    const wrapper = mountList({ busy: true, approvals: [{ ...STOP_APP, label: "Stop an application" }] });

    expect(cards(wrapper)[0]!.find("header strong").text()).toBe("Stop an application");
  });

  it("shows the real arguments, as text", () => {
    const wrapper = mountList({
      busy: true,
      approvals: [{ ...STOP_APP, arguments: { app: "<img src=x onerror=alert(1)>", force: true } }],
    });

    const shown = cards(wrapper)[0]!.find("pre");
    expect(shown.text()).toContain('"app": "<img src=x onerror=alert(1)>"');
    expect(shown.text()).toContain('"force": true');
    expect(cards(wrapper)[0]!.find("img").exists()).toBe(false);
  });

  it("opens short arguments, folds long ones, and says when there are none", () => {
    const short = mountList({ busy: true, approvals: [STOP_APP] });
    expect(cards(short)[0]!.find("details").attributes("open")).toBeDefined();

    const long = mountList({ busy: true, approvals: [{ ...STOP_APP, arguments: { text: "x".repeat(600) } }] });
    expect(cards(long)[0]!.find("details").attributes("open")).toBeUndefined();
    expect(cards(long)[0]!.find("pre").text()).toContain("x".repeat(600)); // still all there to read

    const none = mountList({ busy: true, approvals: [{ ...STOP_APP, arguments: {} }] });
    expect(cards(none)[0]!.find("pre").text()).toBe("(no arguments)");
  });

  it("has three answers, each sent for its own step", async () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP, { ...STOP_APP, id: "step1" }] });
    const [first, second] = cards(wrapper);

    expect(buttons(first!).map((b) => b.text())).toEqual(["Allow once", "Allow for this chat", "Deny"]);
    await buttons(first!)[0]!.trigger("click");
    await buttons(first!)[1]!.trigger("click");
    await buttons(second!)[2]!.trigger("click");

    expect(wrapper.emitted("decide")).toEqual([
      ["step0", "allow"],
      ["step0", "always"],
      ["step1", "deny"],
    ]);
  });

  it("turns the buttons off for a step whose answer is on its way", () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP, { ...STOP_APP, id: "step1" }], deciding: ["step0"] });

    expect(buttons(cards(wrapper)[0]!).every((b) => b.attributes("disabled") !== undefined)).toBe(true);
    expect(buttons(cards(wrapper)[1]!).every((b) => b.attributes("disabled") === undefined)).toBe(true);
  });

  it("does not answer through a disabled button", async () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP], deciding: ["step0"] });

    await buttons(cards(wrapper)[0]!)[0]!.trigger("click");

    expect(wrapper.emitted("decide")).toBeUndefined();
  });

  it("is a labelled group a screen reader can find", () => {
    const wrapper = mountList({ busy: true, approvals: [STOP_APP] });

    expect(cards(wrapper)[0]!.attributes("role")).toBe("group");
    expect(cards(wrapper)[0]!.attributes("aria-label")).toBe("Allow Stop App?");
  });
});
